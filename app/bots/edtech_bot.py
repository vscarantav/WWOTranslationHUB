import os
import json
import hashlib
import re
import shutil
import time
from collections import Counter
from html import escape
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

class EdTechScraperBot:
    TOC_CHAPTER_LINK_SELECTOR = (
        'div#toc > div.toc-row[data-entity-type="chapter"] > a.btn.text-start'
    )
    EDIT_SELECTOR = (
        'a.btn-edit[aria-label="Edit chapter"][href^="/editor/"]:visible'
    )
    HTML_SOURCE_SELECTOR = (
        'div.cm-content[role="textbox"]'
        '[aria-label="Document HTML source"]'
        '[data-language="html"]'
    )
    TITLE_SELECTOR = (
        'h1[contenteditable="plaintext-only"], '
        'h1[contenteditable="true"], '
        '#chapter-title[contenteditable]'
    )
    SUBTITLE_SELECTOR = '#chapter-subtitle[contenteditable]'
    SAVE_SELECTOR = 'button.btn.bi-floppy2-fill:visible'
    CLOSE_SELECTOR = 'button.btn.bi-x-lg.float-end:visible'

    def __init__(self, book_url, target_language, workspace_dir, print_callback=print):
        self.book_url = book_url
        self.target_language = target_language
        self.workspace_dir = workspace_dir
        self.print_callback = print_callback
        self.base_url = "https://books.byui.edu"
        
        # Ensure workspace dirs exist
        self.raw_dir = os.path.join(self.workspace_dir, "raw_html")
        # Let the TranslationController create the translated directory and copy files
        self.translated_dir = os.path.join(self.workspace_dir, f"raw_html_{self.target_language}")
        os.makedirs(self.raw_dir, exist_ok=True)

    def _log_troubleshoot(self, message):
        self.print_callback(f"[EdTech Troubleshoot] {message}")

    def _clear_extraction_files(self):
        """Remove lesson files from an earlier book before starting a new extraction."""
        removed = 0
        for filename in os.listdir(self.raw_dir):
            if re.fullmatch(r"lesson_\d+\.html", filename, flags=re.IGNORECASE):
                os.remove(os.path.join(self.raw_dir, filename))
                removed += 1

        mapping_file = os.path.join(self.workspace_dir, "edtech_mapping.json")
        if os.path.isfile(mapping_file):
            os.remove(mapping_file)

        self._log_troubleshoot(
            f"Cleared {removed} prior extracted lesson file(s) and the prior mapping."
        )

    def reset_translation_output(self):
        """Remove stale translated output so the controller copies this run's source files."""
        workspace_path = os.path.realpath(self.workspace_dir)
        translated_path = os.path.realpath(self.translated_dir)
        if (
            os.path.commonpath([workspace_path, translated_path]) != workspace_path
            or translated_path == workspace_path
        ):
            raise RuntimeError(f"Unsafe EdTech translation output path: {translated_path}")

        if os.path.isdir(translated_path):
            shutil.rmtree(translated_path)
            self._log_troubleshoot(
                f"Removed stale translation output: {translated_path}"
            )
        else:
            self._log_troubleshoot("No stale translation output was present.")

    def load_resumable_injection(self):
        """Return every same-book translated page that is safe to resume."""
        mapping_file = os.path.join(self.workspace_dir, "edtech_mapping.json")
        if not os.path.isfile(mapping_file):
            return []

        try:
            with open(mapping_file, "r", encoding="utf-8") as input_file:
                mapped_pages = json.load(input_file)
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(mapped_pages, list) or not mapped_pages:
            return []

        resumable_pages = []
        for item in mapped_pages:
            if not isinstance(item, dict) or not self._is_url_in_current_book(item.get("url", "")):
                return []
            # Older mappings cannot prove whether a chapter subtitle existed and
            # was included in translation, so they are not safe to resume.
            if "source_subtitle" not in item:
                self._log_troubleshoot(
                    "Saved EdTech translation predates chapter-subtitle support; "
                    "a new extraction and translation are required."
                )
                return []
            if item.get("toc_scope") != "all_chapters":
                self._log_troubleshoot(
                    "Saved EdTech translation contains only leaf lessons and may omit "
                    "top-level chapter pages; a new extraction is required."
                )
                return []

            filename = item.get("filename", "")
            if not re.fullmatch(r"lesson_\d+\.html", filename, flags=re.IGNORECASE):
                return []

            raw_path = os.path.join(self.raw_dir, filename)
            translated_path = os.path.join(self.translated_dir, filename)
            if not os.path.isfile(raw_path):
                return []
            if not os.path.isfile(translated_path):
                self._log_troubleshoot(
                    f"Skipping {filename} during injection resume because its "
                    "translated file is missing."
                )
                continue

            try:
                with open(raw_path, "r", encoding="utf-8") as input_file:
                    raw_html = input_file.read()
                try:
                    with open(translated_path, "r", encoding="utf-8") as input_file:
                        translated_html = input_file.read()
                except OSError as error:
                    self._log_troubleshoot(
                        f"Skipping {filename} during injection resume because its "
                        f"translated file could not be read: {error}"
                    )
                    continue
            except OSError:
                return []

            if raw_html.strip() == translated_html.strip():
                self._log_troubleshoot(
                    f"Skipping {filename} during injection resume because it has no "
                    "completed translation."
                )
                continue
            if item.get("source_title") and not re.search(
                r'<div id="edtech-meta-title"[^>]*>.*?</div>',
                translated_html,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                self._log_troubleshoot(
                    f"Skipping {filename} during injection resume because translated "
                    "title metadata is missing."
                )
                continue
            if item.get("source_subtitle") and not re.search(
                r'<div id="edtech-meta-subtitle"[^>]*>.*?</div>',
                translated_html,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                self._log_troubleshoot(
                    f"Translated subtitle metadata is missing from {filename}; "
                    "that page will be skipped during injection resume."
                )
                continue

            safe_item = dict(item)
            safe_item["raw_filepath"] = raw_path
            safe_item["translated_filepath"] = translated_path
            resumable_pages.append(safe_item)

        self._log_troubleshoot(
            f"Found {len(resumable_pages)} completed translated page(s) eligible for injection resume."
        )
        return resumable_pages

    def _is_url_in_current_book(self, candidate_url):
        book = urlparse(self.book_url)
        candidate = urlparse(candidate_url)
        book_parts = [part for part in book.path.split('/') if part]
        candidate_parts = [part for part in candidate.path.split('/') if part]
        return bool(
            book_parts
            and candidate_parts
            and candidate.scheme in {"http", "https"}
            and candidate.hostname == book.hostname
            and candidate_parts[0] == book_parts[0]
        )

    def _resolve_lesson_url(self, href):
        candidate = urljoin(f"{self.book_url.rstrip('/')}/", href)
        if not self._is_url_in_current_book(candidate):
            self._log_troubleshoot(
                f"REJECTED a TOC link outside the selected book: {candidate}"
            )
            return None
        return candidate

    def _request_action(
        self,
        step_callback,
        *,
        action,
        url,
        page_number,
        page_total,
        selector="",
        details="",
        text_to_copy="",
    ):
        text_digest = (
            hashlib.sha256(text_to_copy.encode("utf-8")).hexdigest()[:12]
            if text_to_copy
            else "none"
        )
        action_state = "WAITING" if step_callback else "AUTOMATIC"
        self._log_troubleshoot(
            f"{action_state} page {page_number}/{page_total}: {action}; URL={url}; "
            f"title={getattr(self, '_current_page_title', '') or 'none'}; "
            f"selector={selector or 'none'}; text_chars={len(text_to_copy)}; "
            f"text_sha256={text_digest}"
        )
        if step_callback:
            approved = step_callback({
                "action": action,
                "url": url,
                "page_number": page_number,
                "page_total": page_total,
                "page_title": getattr(self, "_current_page_title", ""),
                "selector": selector,
                "details": details,
                "text_to_copy": text_to_copy,
            })
            if not approved:
                raise RuntimeError("EdTech injection cancelled from the action window.")
        self._log_troubleshoot(
            f"EXECUTING page {page_number}/{page_total}: {action}"
        )

    @staticmethod
    def _normalized_text(value):
        return re.sub(r"\s+", " ", value or "").strip()

    def _clean_translated_html_for_injection(self, html_content):
        """Remove clipboard markers and make inline word spacing survive EdTech Save."""
        cleaned, comment_marker_count = re.subn(
            r"<!--\s*(?:StartFragment|EndFragment)\s*-->",
            "",
            html_content or "",
            flags=re.IGNORECASE,
        )
        cleaned, visible_marker_count = re.subn(
            r"(?:StartFragment|EndFragment)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        # EdTech can discard newline-only nodes adjacent to inline formatting.
        # Convert a meaningful boundary such as </strong>\nText to an explicit
        # regular space, while keeping punctuation attached to the formatted text.
        cleaned, repaired_space_count = re.subn(
            r"(</(?:strong|b|em|i|u)\s*>)\s+(?=[^<\s,.;:!?%…\)\]\}])",
            r"\1 ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"(</(?:strong|b|em|i|u)\s*>)\s+(?=[,.;:!?%…\)\]\}])",
            r"\1",
            cleaned,
            flags=re.IGNORECASE,
        )

        marker_count = comment_marker_count + visible_marker_count
        if marker_count or repaired_space_count:
            self._log_troubleshoot(
                "Cleaned translated HTML before injection: "
                f"removed_fragment_markers={marker_count}; "
                f"repaired_inline_spaces={repaired_space_count}."
            )
        return cleaned

    @classmethod
    def _semantic_html_signature(cls, html_content, page_url):
        """Represent user-visible content while tolerating HTML serialization changes."""
        soup = BeautifulSoup(html_content or "", "html.parser")
        visible_text = cls._normalized_text(soup.get_text(" ", strip=True))
        meaningful_structure_tags = {
            "h1", "h2", "h3", "h4", "h5", "h6",
            "ul", "ol", "li",
            "table", "tr", "th", "td",
            "a", "img", "audio", "video", "iframe",
            "details", "summary",
        }
        tag_sequence = tuple(
            tag.name
            for tag in soup.find_all(True)
            if tag.name in meaningful_structure_tags
        )
        resource_urls = Counter()
        for tag in soup.find_all(True):
            for attribute in ("href", "src"):
                value = tag.get(attribute)
                if value:
                    resource_urls[(attribute, urljoin(page_url, value))] += 1
        code_blocks = tuple(
            (tag.name, (tag.get_text() or "").replace("\r\n", "\n").strip())
            for tag in soup.find_all(["pre", "code"])
        )
        return {
            "visible_text": visible_text,
            "tag_sequence": tag_sequence,
            "resource_urls": resource_urls,
            "code_blocks": code_blocks,
        }

    @staticmethod
    def _first_text_difference(expected, actual):
        limit = min(len(expected), len(actual))
        index = next(
            (position for position in range(limit) if expected[position] != actual[position]),
            limit,
        )
        start = max(0, index - 80)
        end = index + 160
        return (
            f"difference_at={index}; expected={expected[start:end]!r}; "
            f"saved={actual[start:end]!r}"
        )

    def _write_verification_snapshots(self, item, expected_html, saved_html):
        snapshot_dir = os.path.join(self.workspace_dir, "verification_failures")
        os.makedirs(snapshot_dir, exist_ok=True)
        stem = os.path.splitext(item.get("filename", "page"))[0]
        expected_path = os.path.join(snapshot_dir, f"{stem}_expected.html")
        saved_path = os.path.join(snapshot_dir, f"{stem}_saved.html")
        with open(expected_path, "w", encoding="utf-8") as output_file:
            output_file.write(expected_html)
        with open(saved_path, "w", encoding="utf-8") as output_file:
            output_file.write(saved_html)
        return expected_path, saved_path

    def _verify_saved_html(self, item, page_url, expected_html, saved_html):
        normalize_raw = lambda value: (value or "").replace("\r\n", "\n").strip()
        if normalize_raw(expected_html) == normalize_raw(saved_html):
            self._log_troubleshoot("Save verification matched the raw HTML exactly.")
            return

        expected_hash = hashlib.sha256(expected_html.encode("utf-8")).hexdigest()[:12]
        saved_hash = hashlib.sha256(saved_html.encode("utf-8")).hexdigest()[:12]
        self._log_troubleshoot(
            "Raw HTML serialization changed during Apply/Save: "
            f"expected_chars={len(expected_html)}, expected_sha256={expected_hash}, "
            f"saved_chars={len(saved_html)}, saved_sha256={saved_hash}. "
            "Checking semantic content instead."
        )

        expected = self._semantic_html_signature(expected_html, page_url)
        saved = self._semantic_html_signature(saved_html, page_url)
        mismatches = []
        if expected["visible_text"] != saved["visible_text"]:
            mismatches.append(
                "visible text mismatch ("
                + self._first_text_difference(
                    expected["visible_text"],
                    saved["visible_text"],
                )
                + ")"
            )
        if expected["tag_sequence"] != saved["tag_sequence"]:
            mismatches.append(
                f"HTML structure mismatch (expected {len(expected['tag_sequence'])} tags, "
                f"saved {len(saved['tag_sequence'])} tags)"
            )
        if expected["resource_urls"] != saved["resource_urls"]:
            mismatches.append("link/image URL mismatch")
        if expected["code_blocks"] != saved["code_blocks"]:
            mismatches.append("code/preformatted content mismatch")

        if not mismatches:
            self._log_troubleshoot(
                "VERIFIED semantic HTML match; only benign serialization formatting changed."
            )
            return

        expected_path, saved_path = self._write_verification_snapshots(
            item,
            expected_html,
            saved_html,
        )
        mismatch_summary = "; ".join(mismatches)
        self._log_troubleshoot(
            f"Verification mismatch: {mismatch_summary}. Expected snapshot: {expected_path}. "
            f"Saved snapshot: {saved_path}."
        )
        raise RuntimeError(
            f"Save verification failed for {page_url}: {mismatch_summary}. "
            f"Compare {expected_path} with {saved_path}."
        )

    def _set_chapter_title(self, page, translated_title):
        """Update EdTech's editable title field and commit its change events."""
        title_field = page.locator(self.TITLE_SELECTOR).first
        title_field.wait_for(timeout=10000, state="visible")
        try:
            title_field.fill(translated_title)
            self._log_troubleshoot(
                "Updated the chapter title with Playwright fill()."
            )
        except Exception as fill_error:
            self._log_troubleshoot(
                f"Title fill() was unavailable ({fill_error}); using keyboard input."
            )
            title_field.click()
            title_field.press("Control+A")
            title_field.press_sequentially(translated_title, delay=1)

        title_field.evaluate('''element => {
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.blur();
        }''')
        page.wait_for_timeout(1500)
        saved_value = self._normalized_text(self._read_chapter_title(page))
        if saved_value != self._normalized_text(translated_title):
            raise RuntimeError(
                "The EdTech editor title field rejected the translated title: "
                f"expected {translated_title!r}; field contains {saved_value!r}."
            )

    def _read_chapter_title(self, page):
        title_field = page.locator(self.TITLE_SELECTOR).first
        if title_field.count() == 0:
            return ""
        return title_field.evaluate('''element => {
            if ("value" in element && element.value) return element.value;
            return element.innerText || element.textContent || "";
        }''')

    def _set_chapter_subtitle(self, page, translated_subtitle):
        """Update EdTech's optional editable subtitle and commit its change events."""
        subtitle_field = page.locator(self.SUBTITLE_SELECTOR).first
        subtitle_field.wait_for(timeout=10000, state="visible")
        try:
            subtitle_field.fill(translated_subtitle)
            self._log_troubleshoot(
                "Updated the chapter subtitle with Playwright fill()."
            )
        except Exception as fill_error:
            self._log_troubleshoot(
                f"Subtitle fill() was unavailable ({fill_error}); using keyboard input."
            )
            subtitle_field.click()
            subtitle_field.press("Control+A")
            subtitle_field.press_sequentially(translated_subtitle, delay=1)

        subtitle_field.evaluate('''element => {
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.blur();
        }''')
        page.wait_for_timeout(1500)

    def _read_chapter_subtitle(self, page):
        subtitle_field = page.locator(self.SUBTITLE_SELECTOR).first
        if subtitle_field.count() == 0:
            return ""
        return subtitle_field.evaluate('''element => {
            if ("value" in element && element.value) return element.value;
            return element.innerText || element.textContent || "";
        }''')

    def _open_editor(self, page):
        edit_button = page.locator(self.EDIT_SELECTOR).first
        edit_button.wait_for(timeout=20000, state="visible")
        edit_button.click()
        page.wait_for_url(
            "**/editor/**",
            timeout=60000,
            wait_until="domcontentloaded",
        )

    def _open_html_source(self, page):
        html_button = page.get_by_role("button", name="HTML", exact=True)
        html_button.wait_for(timeout=10000, state="visible")
        html_button.click()
        html_source = page.locator(self.HTML_SOURCE_SELECTOR)
        html_source.wait_for(timeout=10000, state="visible")
        return html_source

    @staticmethod
    def _copy_full_html_source(page, html_source):
        page.evaluate("() => navigator.clipboard.writeText('')")
        html_source.click()
        html_source.press("Control+A")
        html_source.press("Control+C")
        page.wait_for_function(
            """async () => Boolean((await navigator.clipboard.readText()).trim())""",
            timeout=10000,
        )
        return page.evaluate("() => navigator.clipboard.readText()")

    def _replace_full_html_source(self, page, html_source, translated_html):
        page.evaluate("(html) => navigator.clipboard.writeText(html)", translated_html)
        html_source.click()
        html_source.press("Control+A")
        html_source.press("Control+V")
        page.wait_for_timeout(750)
        pasted_html = self._copy_full_html_source(page, html_source)
        normalize = lambda value: (value or "").replace("\r\n", "\n").strip()
        if normalize(pasted_html) != normalize(translated_html):
            raise RuntimeError(
                "CodeMirror did not retain the complete translated HTML."
            )

    def _close_editor(self, page, public_url):
        close_button = page.locator(self.CLOSE_SELECTOR).first
        close_button.wait_for(timeout=10000, state="visible")
        close_button.click()
        page.wait_for_url(
            lambda url: str(url).rstrip("/") == public_url.rstrip("/"),
            timeout=60000,
            wait_until="domcontentloaded",
        )

    @staticmethod
    def _lesson_number(item):
        match = re.fullmatch(
            r"lesson_(\d+)\.html",
            item.get("filename", ""),
            flags=re.IGNORECASE,
        )
        if not match:
            raise RuntimeError(
                f"Invalid EdTech lesson filename: {item.get('filename', '')!r}."
            )
        return int(match.group(1))

    def _read_live_toc(self, page):
        page.goto(
            self.book_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_selector("#toc", timeout=60000, state="visible")
        links = page.locator(self.TOC_CHAPTER_LINK_SELECTOR)
        entries = []
        for index in range(links.count()):
            link = links.nth(index)
            href = link.get_attribute("href")
            url = self._resolve_lesson_url(href) if href else None
            if not url:
                raise RuntimeError(
                    f"The live TOC contains an invalid chapter link at position {index + 1}."
                )
            entries.append({
                "url": url,
                "title": self._normalized_text(link.inner_text()),
            })
        if not entries:
            raise RuntimeError("The selected EdTech book has no chapter links in its TOC.")
        return entries

    def _translated_title_from_file(self, item):
        translated_path = item.get("translated_filepath", "")
        if not translated_path or not os.path.isfile(translated_path):
            return ""
        try:
            with open(translated_path, "r", encoding="utf-8") as input_file:
                translated_html = input_file.read()
        except OSError:
            return ""
        match = re.search(
            r'<div id="edtech-meta-title"[^>]*>(.*?)</div>',
            translated_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        return self._normalized_text(
            BeautifulSoup(match.group(1), "html.parser").get_text(" ", strip=True)
        )

    def _refresh_injection_urls(self, page, extracted_files):
        """Remap lesson_N files to the current TOC after validating their titles."""
        live_entries = self._read_live_toc(page)
        refreshed = []
        for item in extracted_files:
            lesson_number = self._lesson_number(item)
            if lesson_number > len(live_entries):
                raise RuntimeError(
                    f"{item['filename']} expects TOC position {lesson_number}, but the "
                    f"live book has only {len(live_entries)} chapter(s)."
                )
            live_entry = live_entries[lesson_number - 1]
            expected_titles = {
                self._normalized_text(item.get("source_title", "")).casefold(),
                self._translated_title_from_file(item).casefold(),
            } - {""}
            live_title = self._normalized_text(live_entry["title"])
            if expected_titles and live_title.casefold() not in expected_titles:
                raise RuntimeError(
                    f"TOC mismatch for {item['filename']}: the live title "
                    f"{live_title!r} matches neither its source nor translated title."
                )
            current_item = dict(item)
            current_item["url"] = live_entry["url"]
            refreshed.append(current_item)

        mapping_path = os.path.join(self.workspace_dir, "edtech_mapping.json")
        try:
            with open(mapping_path, "r", encoding="utf-8") as input_file:
                full_mapping = json.load(input_file)
        except (OSError, json.JSONDecodeError):
            full_mapping = list(refreshed)
        if isinstance(full_mapping, list):
            for mapped_item in full_mapping:
                try:
                    lesson_number = self._lesson_number(mapped_item)
                except RuntimeError:
                    continue
                if lesson_number <= len(live_entries):
                    mapped_item["url"] = live_entries[lesson_number - 1]["url"]
            self._write_extraction_mapping(full_mapping)

        self._log_troubleshoot(
            f"Validated the live TOC and refreshed {len(refreshed)} injection URL(s)."
        )
        return refreshed

    def _open_toc_item(self, page, item):
        toc_index = self._lesson_number(item) - 1
        page.goto(
            self.book_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_selector("#toc", timeout=60000, state="visible")
        link = page.locator(self.TOC_CHAPTER_LINK_SELECTOR).nth(toc_index)
        link.wait_for(timeout=20000, state="visible")
        link.click()
        page.wait_for_url(
            lambda url: str(url).rstrip("/") == item["url"].rstrip("/"),
            timeout=60000,
            wait_until="domcontentloaded",
        )

    def _prepare_translated_page(self, item):
        translated_path = item.get("translated_filepath", "")
        if not os.path.isfile(translated_path):
            raise RuntimeError(
                f"Translated file not found for {item.get('url', '')}: {translated_path}"
            )
        with open(translated_path, "r", encoding="utf-8") as input_file:
            translated_html = self._clean_translated_html_for_injection(
                input_file.read()
            )

        def extract_metadata(element_id, required, label):
            nonlocal translated_html
            match = re.search(
                rf'<div id="{element_id}"[^>]*>(.*?)</div>',
                translated_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not match:
                if required:
                    raise RuntimeError(
                        f"Translated {label} is missing for {item.get('url', '')}."
                    )
                return None
            value = self._normalized_text(
                BeautifulSoup(match.group(1), "html.parser").get_text(" ", strip=True)
            )
            if not value:
                raise RuntimeError(
                    f"Translated {label} is empty for {item.get('url', '')}."
                )
            translated_html = (
                translated_html[:match.start()] + translated_html[match.end():]
            ).strip()
            return value

        translated_title = extract_metadata(
            "edtech-meta-title",
            bool(item.get("source_title")),
            "title",
        )
        translated_subtitle = extract_metadata(
            "edtech-meta-subtitle",
            bool(item.get("source_subtitle")),
            "subtitle",
        )
        return translated_title, translated_subtitle, translated_html

    def _launch_anonymous_context(self, playwright):
        """Launch a fresh, non-persistent browser context with no saved session data."""
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            no_viewport=True,
            permissions=["clipboard-read", "clipboard-write"],
        )
        context.clear_cookies()
        self.print_callback(
            "Launched a fresh anonymous browser session. "
            "Cookies and login state will not be saved."
        )
        return browser, context

    def _extract_chapter(self, page, url, index, toc_title=""):
        """Read one chapter through EdTech's current HTML editor."""
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        self._open_editor(page)

        title_text = ""
        try:
            page.locator(self.TITLE_SELECTOR).first.wait_for(
                timeout=10000,
                state="visible",
            )
            title_text = self._normalized_text(self._read_chapter_title(page))
        except Exception as title_error:
            self._log_troubleshoot(
                f"Could not read the editor title for {url} ({title_error}); "
                "using the validated TOC title."
            )
        title_text = title_text or self._normalized_text(toc_title)
        if not title_text:
            raise RuntimeError(f"No chapter title was available for {url}.")

        subtitle_text = ""
        subtitle_field = page.locator(self.SUBTITLE_SELECTOR).first
        if subtitle_field.count():
            try:
                subtitle_text = self._normalized_text(
                    self._read_chapter_subtitle(page)
                )
            except Exception as subtitle_error:
                self._log_troubleshoot(
                    f"Could not read the optional subtitle for {url}: {subtitle_error}"
                )

        html_source = self._open_html_source(page)
        visible_html = html_source.inner_text()
        html_content = self._copy_full_html_source(page, html_source)
        if not html_content or not html_content.strip():
            raise RuntimeError("CodeMirror did not copy any HTML to the clipboard.")
        if len(html_content) < len(visible_html):
            raise RuntimeError(
                "The copied HTML was shorter than CodeMirror's visible DOM; "
                "refusing to save an incomplete page."
            )
        self._close_editor(page, url)

        metadata_parts = [
            '<div id="edtech-meta-title" style="display:none;">'
            f'{escape(title_text, quote=False)}</div>'
        ]
        if subtitle_text:
            metadata_parts.append(
                '<div id="edtech-meta-subtitle" style="display:none;">'
                f'{escape(subtitle_text, quote=False)}</div>'
            )
        html_content = f"{chr(10).join(metadata_parts)}\n{html_content}"

        filename = f"lesson_{index}.html"
        filepath = os.path.join(self.raw_dir, filename)
        with open(filepath, "w", encoding="utf-8") as output_file:
            output_file.write(html_content)

        self._log_troubleshoot(
            f"Copied {len(html_content)} HTML character(s) for {filename}."
        )
        return {
            "url": url,
            "filename": filename,
            "source_title": title_text,
            "source_subtitle": subtitle_text,
            "toc_scope": "all_chapters",
            "raw_filepath": filepath,
            "translated_filepath": os.path.join(self.translated_dir, filename),
        }
    def _write_extraction_mapping(self, extracted_files):
        mapping_path = os.path.join(self.workspace_dir, "edtech_mapping.json")
        temporary_path = mapping_path + ".tmp"
        with open(temporary_path, "w", encoding="utf-8") as mapping_file:
            json.dump(
                extracted_files,
                mapping_file,
                ensure_ascii=False,
                indent=4,
            )
        os.replace(temporary_path, mapping_path)

    def _google_login_transition_started(self, page, logged_in_selector):
        """Return True when a click error was caused by OAuth navigation starting."""
        try:
            current_url = page.url or ""
        except Exception:
            current_url = ""

        current_host = (urlparse(current_url).hostname or "").lower()
        edtech_host = (urlparse(self.base_url).hostname or "").lower()
        if current_host and current_host != edtech_host:
            self._log_troubleshoot(
                "Google SSO navigation started before the click command returned; "
                f"continuing on {current_host}."
            )
            return True

        try:
            if page.locator(logged_in_selector).is_visible():
                self._log_troubleshoot(
                    "EdTech already shows the signed-in account control after the Google click."
                )
                return True
        except Exception:
            pass

        return False

    def _start_google_login(self, page, google_btn_selector, logged_in_selector):
        """Start same-tab Google OAuth without Playwright waiting on that navigation."""
        try:
            clicked = page.evaluate(
                '''(selector) => {
                    const button = document.querySelector(selector);
                    if (!button) return false;
                    button.click();
                    return true;
                }''',
                google_btn_selector,
            )
        except Exception as click_error:
            if self._google_login_transition_started(page, logged_in_selector):
                return
            raise RuntimeError(
                "Could not start Google SSO from the EdTech login dialog: "
                f"{click_error}"
            ) from click_error

        if not clicked:
            if self._google_login_transition_started(page, logged_in_selector):
                return
            raise RuntimeError(
                "The Google Login button disappeared before it could be clicked. "
                "Open the EdTech login dialog again and retry."
            )

        self._log_troubleshoot(
            "Triggered the Google Login button without waiting on its same-tab OAuth navigation."
        )

    def _ensure_login(self, page):
        """Ensures the user is logged in by navigating to the base URL and checking the login button."""
        self.print_callback(f"Navigating to base URL for login check: {self.base_url}")
        page.goto(self.base_url, timeout=60000)
        
        # Give the website 3 seconds to verify the session and replace the login button with the user profile
        time.sleep(3)
        
        login_selector = 'button#user-link[data-target-template="modal-login"]'
        logged_in_selector = 'button#user-link[data-bs-toggle="dropdown"]'

        try:
            page.wait_for_selector(
                f"{login_selector}, {logged_in_selector}",
                timeout=30000,
                state="visible",
            )
        except Exception as state_error:
            raise RuntimeError(
                "EdTech did not display either the login button or the signed-in "
                f"account menu: {state_error}"
            ) from state_error

        needs_login = page.locator(login_selector).is_visible()
        login_confirmed = page.locator(logged_in_selector).is_visible()
        
        if needs_login:
            self.print_callback("Login button detected. Initiating Google Login flow...")
            try:
                # Click the user link
                page.click(login_selector)
                
                # Wait for Google login button in modal
                google_btn_selector = 'button[data-action="LoginGoogle"]'
                page.wait_for_selector(google_btn_selector, timeout=5000, state="visible")
                self._start_google_login(
                    page,
                    google_btn_selector,
                    logged_in_selector,
                )
                
                self.print_callback("Please complete the Google SSO login in the browser...")
                self.print_callback("Waiting for the EdTech account menu to confirm login...")

                # A successful SSO flow does not always return to the exact homepage URL.
                # Waiting for the logged-in account control avoids a false three-minute stall.
                page.wait_for_selector(logged_in_selector, timeout=180000, state="visible")
                
                # Wait a moment for the post-login homepage to fully render
                time.sleep(3)
                self.print_callback("Login confirmed! Proceeding...")
            except Exception as e:
                raise RuntimeError(f"EdTech login was not confirmed: {e}") from e
        elif login_confirmed:
            self.print_callback("Already logged in.")
        else:
            raise RuntimeError(
                "EdTech login state could not be determined after the page finished loading."
            )

    def run_extraction(self):
        """Extracts all HTML from the book lessons."""
        extracted_files = []
        failures = []
        self._clear_extraction_files()
        self.print_callback(f"Starting Playwright for EdTech extraction...")

        with sync_playwright() as p:
            self.print_callback("Launching browser. Please log in if prompted...")
            browser, context = self._launch_anonymous_context(p)
            try:
                page = context.new_page()

                # Ensure logged in before navigating to the specific book URL.
                self._ensure_login(page)

                self.print_callback(
                    f"Navigating to target book shell: {self.book_url}"
                )
                page.goto(
                    self.book_url,
                    timeout=60000,
                    wait_until="domcontentloaded",
                )

                try:
                    page.wait_for_selector('div#toc', timeout=10000)
                except Exception:
                    self.print_callback("TOC not found immediately. Waiting...")
                    page.wait_for_selector('div#toc', timeout=60000)

                self.print_callback("Parsing Table of Contents...")

                # Every chapter row is an editable page. Include both parent
                # chapters and leaf lessons, and retain TOC text as a title fallback.
                page.wait_for_selector(
                    self.TOC_CHAPTER_LINK_SELECTOR,
                    timeout=20000,
                    state="visible",
                )
                locators = page.locator(self.TOC_CHAPTER_LINK_SELECTOR).all()

                chapters = []
                seen_urls = set()
                for locator in locators:
                    href = locator.get_attribute('href')
                    lesson_url = self._resolve_lesson_url(href) if href else None
                    if lesson_url and lesson_url not in seen_urls:
                        seen_urls.add(lesson_url)
                        chapters.append({
                            "url": lesson_url,
                            "title": self._normalized_text(locator.inner_text()),
                        })

                self.print_callback(
                    f"Found {len(chapters)} chapter page(s) to extract."
                )

                for index, chapter in enumerate(chapters, start=1):
                    url = chapter["url"]
                    self.print_callback(
                        f"Extracting [{index}/{len(chapters)}]: {url}"
                    )
                    try:
                        extracted_files.append(
                            self._extract_chapter(
                                page,
                                url,
                                index,
                                toc_title=chapter["title"],
                            )
                        )
                        self._write_extraction_mapping(extracted_files)
                    except Exception as extraction_error:
                        failures.append(f"{url}: {extraction_error}")
                        self.print_callback(
                            f"FAILED [{index}/{len(chapters)}]: {extraction_error}"
                        )
                        if page.is_closed():
                            self.print_callback(
                                "Browser window was closed; stopping extraction."
                            )
                            break
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

        self._write_extraction_mapping(extracted_files)
        if failures:
            failure_details = "\n".join(f"- {failure}" for failure in failures)
            raise RuntimeError(
                f"Extracted {len(extracted_files)} page(s), but "
                f"{len(failures)} page(s) failed:\n{failure_details}"
            )

        return extracted_files

    def run_injection(self, extracted_files=None, step_callback=None):
        """Inject translated HTML through EdTech's current editor and verify it."""
        self.print_callback("Starting Playwright injection into the target book shell...")

        if extracted_files is None:
            mapping_file = os.path.join(self.workspace_dir, "edtech_mapping.json")
            if not os.path.exists(mapping_file):
                raise RuntimeError("Mapping file not found. Cannot inject.")
            with open(mapping_file, "r", encoding="utf-8") as input_file:
                extracted_files = json.load(input_file)
        else:
            extracted_files = list(extracted_files)

        if not extracted_files:
            raise RuntimeError("No current-run EdTech pages are available to inject.")
        for item in extracted_files:
            if not self._is_url_in_current_book(item.get("url", "")):
                raise RuntimeError(
                    "Refusing to inject a page outside the selected book: "
                    f"{item.get('url', '')}"
                )

        with sync_playwright() as playwright:
            browser, context = self._launch_anonymous_context(playwright)
            page = context.new_page()
            try:
                self._ensure_login(page)
                extracted_files = self._refresh_injection_urls(
                    page,
                    extracted_files,
                )
                page_total = len(extracted_files)

                for page_number, item in enumerate(extracted_files, start=1):
                    url = item["url"]
                    (
                        translated_title,
                        translated_subtitle,
                        translated_html,
                    ) = self._prepare_translated_page(item)
                    self._current_page_title = (
                        translated_title
                        or item.get("source_title")
                        or item.get("filename")
                        or "Untitled page"
                    )

                    self._request_action(
                        step_callback,
                        action="Open the current chapter from the live TOC",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.TOC_CHAPTER_LINK_SELECTOR,
                        details=(
                            "Open the target book and select the chapter at the "
                            "validated lesson_N TOC position."
                        ),
                    )
                    self._open_toc_item(page, item)

                    self._request_action(
                        step_callback,
                        action='Click "Edit"',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.EDIT_SELECTOR,
                        details="Open the current chapter editor.",
                    )
                    self._open_editor(page)

                    if translated_title:
                        self._request_action(
                            step_callback,
                            action="Replace the translated chapter title",
                            url=url,
                            page_number=page_number,
                            page_total=page_total,
                            selector=self.TITLE_SELECTOR,
                            details=(
                                "Fill the editor's contenteditable h1 and commit "
                                "its change event before Save."
                            ),
                            text_to_copy=translated_title,
                        )
                        self._set_chapter_title(page, translated_title)

                    if translated_subtitle:
                        self._request_action(
                            step_callback,
                            action="Replace the translated chapter subtitle",
                            url=url,
                            page_number=page_number,
                            page_total=page_total,
                            selector=self.SUBTITLE_SELECTOR,
                            details=(
                                "Fill the optional subtitle and commit its change "
                                "event before Save."
                            ),
                            text_to_copy=translated_subtitle,
                        )
                        self._set_chapter_subtitle(page, translated_subtitle)

                    self._request_action(
                        step_callback,
                        action='Click "HTML"',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector='button:has-text("HTML")',
                        details="Open the CodeMirror HTML source editor.",
                    )
                    html_source = self._open_html_source(page)

                    self._request_action(
                        step_callback,
                        action="Replace the complete HTML source",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.HTML_SOURCE_SELECTOR,
                        details=(
                            "Select all CodeMirror content and paste the complete "
                            "translated HTML through the clipboard."
                        ),
                        text_to_copy=translated_html,
                    )
                    self._replace_full_html_source(
                        page,
                        html_source,
                        translated_html,
                    )

                    self._request_action(
                        step_callback,
                        action='Click "Save"',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.SAVE_SELECTOR,
                        details="Save the translated title, subtitle, and HTML.",
                    )
                    save_button = page.locator(self.SAVE_SELECTOR).first
                    save_button.wait_for(timeout=10000, state="visible")
                    save_button.click()
                    page.wait_for_timeout(3000)

                    self._request_action(
                        step_callback,
                        action="Close the editor",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.CLOSE_SELECTOR,
                        details="Return to the public chapter before verification.",
                    )
                    self._close_editor(page, url)

                    self._request_action(
                        step_callback,
                        action="Reopen the editor for save verification",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.EDIT_SELECTOR,
                        details="Reopen the saved chapter without changing it.",
                    )
                    self._open_editor(page)

                    if translated_title:
                        page.locator(self.TITLE_SELECTOR).first.wait_for(
                            timeout=10000,
                            state="visible",
                        )
                    saved_title = self._read_chapter_title(page)
                    saved_subtitle = self._read_chapter_subtitle(page)

                    self._request_action(
                        step_callback,
                        action='Click "HTML" for save verification',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector='button:has-text("HTML")',
                        details="Open the persisted CodeMirror HTML source.",
                    )
                    saved_source = self._open_html_source(page)
                    saved_html = self._copy_full_html_source(page, saved_source)

                    self._verify_saved_html(
                        item,
                        url,
                        translated_html,
                        saved_html,
                    )
                    if (
                        translated_title
                        and self._normalized_text(saved_title)
                        != self._normalized_text(translated_title)
                    ):
                        raise RuntimeError(
                            f"Save verification failed for {url}: persisted title "
                            f"does not match. Expected {translated_title!r}; "
                            f"saved {saved_title!r}."
                        )
                    if (
                        translated_subtitle
                        and self._normalized_text(saved_subtitle)
                        != self._normalized_text(translated_subtitle)
                    ):
                        raise RuntimeError(
                            f"Save verification failed for {url}: persisted subtitle "
                            f"does not match. Expected {translated_subtitle!r}; "
                            f"saved {saved_subtitle!r}."
                        )

                    self._request_action(
                        step_callback,
                        action="Close the verified editor",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=self.CLOSE_SELECTOR,
                        details="Close the verified chapter before continuing.",
                    )
                    self._close_editor(page, url)
                    self._log_troubleshoot(
                        f"VERIFIED page {page_number}/{page_total}: saved HTML, "
                        "title, and optional subtitle match."
                    )
            except Exception as exc:
                self._log_troubleshoot(f"STOPPED: {type(exc).__name__}: {exc}")
                raise
            finally:
                context.close()
                browser.close()

        self.print_callback("Injection complete. Every page passed save verification.")
