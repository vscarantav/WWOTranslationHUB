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
        """Return a complete, same-book translated mapping that is safe to resume."""
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
            if not os.path.isfile(raw_path) or not os.path.isfile(translated_path):
                return []

            try:
                with open(raw_path, "r", encoding="utf-8") as input_file:
                    raw_html = input_file.read()
                with open(translated_path, "r", encoding="utf-8") as input_file:
                    translated_html = input_file.read()
            except OSError:
                return []

            if raw_html.strip() == translated_html.strip():
                return []
            if item.get("source_title") and not re.search(
                r'<div id="edtech-meta-title"[^>]*>.*?</div>',
                translated_html,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                return []
            if item.get("source_subtitle") and not re.search(
                r'<div id="edtech-meta-subtitle"[^>]*>.*?</div>',
                translated_html,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                self._log_troubleshoot(
                    f"Translated subtitle metadata is missing from {filename}; "
                    "the saved injection cannot be resumed safely."
                )
                return []

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
        title_selector = "#chapter-title"
        title_field = page.locator(title_selector)
        try:
            title_field.fill(translated_title)
            self._log_troubleshoot(
                "Updated the chapter title with Playwright fill()."
            )
        except Exception as fill_error:
            self._log_troubleshoot(
                f"Title fill() was unavailable ({fill_error}); using the DOM fallback."
            )
            page.evaluate('''(title) => {
                const el = document.getElementById("chapter-title");
                if (!el) throw new Error("chapter-title was not found");
                if ("value" in el) el.value = title;
                el.textContent = title;
                el.innerText = title;
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }''', translated_title)

        page.evaluate('''() => {
            const el = document.getElementById("chapter-title");
            if (!el) throw new Error("chapter-title was not found");
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.blur();
        }''')
        page.wait_for_timeout(500)

    @staticmethod
    def _read_chapter_title(page):
        return page.evaluate('''() => {
            const el = document.getElementById("chapter-title");
            if (!el) return "";
            if ("value" in el && el.value) return el.value;
            return el.innerText || el.textContent || "";
        }''')

    def _set_chapter_subtitle(self, page, translated_subtitle):
        """Update EdTech's optional editable subtitle and commit its change events."""
        subtitle_selector = "#chapter-subtitle"
        subtitle_field = page.locator(subtitle_selector)
        try:
            subtitle_field.fill(translated_subtitle)
            self._log_troubleshoot(
                "Updated the chapter subtitle with Playwright fill()."
            )
        except Exception as fill_error:
            self._log_troubleshoot(
                f"Subtitle fill() was unavailable ({fill_error}); using the DOM fallback."
            )
            page.evaluate('''(subtitle) => {
                const el = document.getElementById("chapter-subtitle");
                if (!el) throw new Error("chapter-subtitle was not found");
                if ("value" in el) el.value = subtitle;
                el.textContent = subtitle;
                el.innerText = subtitle;
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }''', translated_subtitle)

        page.evaluate('''() => {
            const el = document.getElementById("chapter-subtitle");
            if (!el) throw new Error("chapter-subtitle was not found");
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.blur();
        }''')
        page.wait_for_timeout(500)

    @staticmethod
    def _read_chapter_subtitle(page):
        return page.evaluate('''() => {
            const el = document.getElementById("chapter-subtitle");
            if (!el) return "";
            if ("value" in el && el.value) return el.value;
            return el.innerText || el.textContent || "";
        }''')

    def _launch_anonymous_context(self, playwright):
        """Launch a fresh, non-persistent browser context with no saved session data."""
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(no_viewport=True)
        context.clear_cookies()
        self.print_callback(
            "Launched a fresh anonymous browser session. "
            "Cookies and login state will not be saved."
        )
        return browser, context

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
        self._clear_extraction_files()
        self.print_callback(f"Starting Playwright for EdTech extraction...")

        with sync_playwright() as p:
            self.print_callback("Launching browser. Please log in if prompted...")
            browser, context = self._launch_anonymous_context(p)
            page = context.new_page()
            
            # Ensure logged in before navigating to the specific book URL
            self._ensure_login(page)
            
            self.print_callback(f"Navigating to target book shell: {self.book_url}")
            page.goto(self.book_url, timeout=60000)
            
            try:
                page.wait_for_selector('div#toc', timeout=10000)
            except:
                self.print_callback("TOC not found immediately. Waiting...")
                page.wait_for_selector('div#toc', timeout=60000)

            self.print_callback("Parsing Table of Contents...")
            
            # Every chapter row is an editable page. Include both parent chapters
            # (nonempty data-children) and leaf lessons (empty data-children).
            page.wait_for_selector(
                self.TOC_CHAPTER_LINK_SELECTOR,
                timeout=20000,
                state="visible",
            )
            locators = page.locator(self.TOC_CHAPTER_LINK_SELECTOR).all()
            
            lesson_urls = []
            for loc in locators:
                href = loc.get_attribute('href')
                if href:
                    lesson_url = self._resolve_lesson_url(href)
                    if lesson_url and lesson_url not in lesson_urls:
                        lesson_urls.append(lesson_url)
            
            self.print_callback(
                f"Found {len(lesson_urls)} chapter page(s) to extract."
            )
            
            for index, url in enumerate(lesson_urls):
                self.print_callback(f"Extracting [{index+1}/{len(lesson_urls)}]: {url}")
                page.goto(url)
                
                # 1. Click "Edit"
                try:
                    page.wait_for_selector('button[data-action="ToggleEditor"]', timeout=10000)
                    page.click('button[data-action="ToggleEditor"]')
                except:
                    self.print_callback(f"Could not find Edit button on {url}. Skipping.")
                    continue

                # Read the editable chapter title from the same h1 that will be
                # updated during injection. Do this before opening the HTML tray.
                try:
                    page.wait_for_selector(
                        'h1#chapter-title[contenteditable]',
                        timeout=5000,
                        state="visible",
                    )
                    title_text = self._normalized_text(
                        self._read_chapter_title(page)
                    )
                    if not title_text:
                        raise RuntimeError("the editable chapter title is empty")
                    self._log_troubleshoot(
                        f"Extracted chapter title from h1#chapter-title: {title_text!r}"
                    )
                    subtitle_text = self._normalized_text(
                        self._read_chapter_subtitle(page)
                    )
                    if subtitle_text:
                        self._log_troubleshoot(
                            "Extracted chapter subtitle from "
                            f"p#chapter-subtitle: {subtitle_text!r}"
                        )
                except Exception as title_error:
                    self.print_callback(
                        f"Could not extract the editable chapter title on {url}: "
                        f"{title_error}. Skipping."
                    )
                    continue
                
                # 2. Click "Edit HTML"
                try:
                    page.wait_for_selector('button.bi-code[data-target="#editor-tray-code-box"]', timeout=5000)
                    page.click('button.bi-code[data-target="#editor-tray-code-box"]')
                except:
                    self.print_callback(f"Could not find Edit HTML button on {url}. Skipping.")
                    continue
                
                # 3. Extract HTML from code-box
                try:
                    page.wait_for_selector('div#code-box', timeout=5000)
                    html_content = page.evaluate('document.getElementById("code-box").innerText')
                    
                    # Prepend the title as a hidden tag so the TranslationController
                    # translates it along with the chapter body. Escape it because the
                    # source h1 is plaintext-only while this carrier is HTML.
                    title_for_html = escape(title_text, quote=False)
                    metadata_html = (
                        '<div id="edtech-meta-title" style="display:none;">'
                        f'{title_for_html}</div>'
                    )
                    if subtitle_text:
                        subtitle_for_html = escape(subtitle_text, quote=False)
                        metadata_html += (
                            '\n<div id="edtech-meta-subtitle" style="display:none;">'
                            f'{subtitle_for_html}</div>'
                        )
                    html_content = f"{metadata_html}\n{html_content}"
                    
                    filename = f"lesson_{index+1}.html"
                    filepath = os.path.join(self.raw_dir, filename)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    
                    extracted_files.append({
                        "url": url,
                        "filename": filename,
                        "source_title": title_text,
                        "source_subtitle": subtitle_text,
                        "toc_scope": "all_chapters",
                        "raw_filepath": filepath,
                        "translated_filepath": os.path.join(self.translated_dir, filename)
                    })
                except Exception as e:
                    self.print_callback(f"Error extracting HTML on {url}: {e}")
                    
            context.close()
            browser.close()
            
            with open(os.path.join(self.workspace_dir, "edtech_mapping.json"), 'w', encoding='utf-8') as f:
                json.dump(extracted_files, f, indent=4)
                
        return extracted_files

    def run_injection(self, extracted_files=None, step_callback=None):
        """Inject translated HTML automatically and verify each saved page."""
        self.print_callback("Starting Playwright injection into the target book shell...")

        if extracted_files is None:
            mapping_file = os.path.join(self.workspace_dir, "edtech_mapping.json")
            if not os.path.exists(mapping_file):
                raise RuntimeError("Mapping file not found. Cannot inject.")
            with open(mapping_file, 'r', encoding='utf-8') as f:
                extracted_files = json.load(f)
        else:
            # Use the current run's in-memory mapping. This prevents an old mapping
            # from another book from being injected accidentally.
            extracted_files = list(extracted_files)

        if not extracted_files:
            raise RuntimeError("No current-run EdTech pages are available to inject.")

        for item in extracted_files:
            if not self._is_url_in_current_book(item.get('url', '')):
                raise RuntimeError(
                    f"Refusing to inject a page outside the selected book: {item.get('url', '')}"
                )

        edit_selector = 'button[data-action="ToggleEditor"]'
        html_selector = 'button.bi-code[data-target="#editor-tray-code-box"]'
        code_selector = 'div#code-box'
        apply_selector = 'button[data-custom-action="ApplyCode"]'
        save_selector = 'button[data-ribbon-action="Save"]'

        with sync_playwright() as p:
            browser, context = self._launch_anonymous_context(p)
            page = context.new_page()
            try:
                # Complete browser setup and authentication before presenting any
                # controlled injection actions in the troubleshooting window.
                self._ensure_login(page)
                page_total = len(extracted_files)

                for page_number, item in enumerate(extracted_files, start=1):
                    url = item['url']
                    translated_path = item['translated_filepath']
                    if not os.path.isfile(translated_path):
                        raise RuntimeError(f"Translated file not found for {url}: {translated_path}")

                    with open(translated_path, 'r', encoding='utf-8') as f:
                        translated_html = self._clean_translated_html_for_injection(
                            f.read()
                        )

                    title_match = re.search(
                        r'<div id="edtech-meta-title"[^>]*>(.*?)</div>',
                        translated_html,
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                    translated_title = None
                    if title_match:
                        translated_title = self._normalized_text(
                            BeautifulSoup(
                                title_match.group(1),
                                "html.parser",
                            ).get_text(" ", strip=True)
                        )
                        if not translated_title:
                            raise RuntimeError(
                                f"Translated title is empty for {url}; refusing to leave its English title in place."
                            )
                        translated_html = (
                            translated_html[:title_match.start()]
                            + translated_html[title_match.end():]
                        ).strip()
                    elif item.get("source_title"):
                        raise RuntimeError(
                            f"Translated title is missing for {url}; refusing to leave its English title in place."
                        )

                    subtitle_match = re.search(
                        r'<div id="edtech-meta-subtitle"[^>]*>(.*?)</div>',
                        translated_html,
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                    translated_subtitle = None
                    if subtitle_match:
                        translated_subtitle = self._normalized_text(
                            BeautifulSoup(
                                subtitle_match.group(1),
                                "html.parser",
                            ).get_text(" ", strip=True)
                        )
                        if not translated_subtitle:
                            raise RuntimeError(
                                f"Translated subtitle is empty for {url}; refusing to leave its English subtitle in place."
                            )
                        translated_html = (
                            translated_html[:subtitle_match.start()]
                            + translated_html[subtitle_match.end():]
                        ).strip()
                    elif item.get("source_subtitle"):
                        raise RuntimeError(
                            f"Translated subtitle is missing for {url}; refusing to leave its English subtitle in place."
                        )

                    self._current_page_title = (
                        translated_title
                        or item.get("source_title")
                        or item.get("filename")
                        or "Untitled page"
                    )

                    self._request_action(
                        step_callback,
                        action="Navigate to the target EdTech page",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        details="Open this exact URL from the current book mapping.",
                    )
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)

                    self._request_action(
                        step_callback,
                        action='Click "Edit"',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=edit_selector,
                        details="Open the chapter editor.",
                    )
                    page.wait_for_selector(edit_selector, timeout=20000, state="visible")
                    page.click(edit_selector)

                    self._request_action(
                        step_callback,
                        action='Click "Edit HTML"',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=html_selector,
                        details="Open the raw HTML code box.",
                    )
                    page.wait_for_selector(html_selector, timeout=10000, state="visible")
                    page.click(html_selector)

                    self._request_action(
                        step_callback,
                        action="Copy translated HTML into the code box",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=code_selector,
                        details="Replace the code-box text with the exact HTML shown below.",
                        text_to_copy=translated_html,
                    )
                    page.wait_for_selector(code_selector, timeout=10000, state="visible")
                    page.evaluate('''(htmlContent) => {
                        const box = document.getElementById("code-box");
                        box.innerText = htmlContent;
                        box.dispatchEvent(new Event('input', { bubbles: true }));
                    }''', translated_html)

                    self._request_action(
                        step_callback,
                        action='Click "Apply"',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=apply_selector,
                        details="Apply the raw HTML to the visual editor.",
                    )
                    page.wait_for_selector(apply_selector, timeout=10000, state="visible")
                    page.click(apply_selector)
                    page.wait_for_timeout(1500)

                    if translated_title:
                        self._request_action(
                            step_callback,
                            action="Copy the translated chapter title",
                            url=url,
                            page_number=page_number,
                            page_total=page_total,
                            selector="h1#chapter-title[contenteditable]",
                            details=(
                                "After applying the translated HTML, replace the editable "
                                "chapter title and commit its input/change events before Save."
                            ),
                            text_to_copy=translated_title,
                        )
                        page.wait_for_selector(
                            'h1#chapter-title[contenteditable]',
                            timeout=10000,
                            state="visible",
                        )
                        self._set_chapter_title(page, translated_title)

                    if translated_subtitle:
                        self._request_action(
                            step_callback,
                            action="Copy the translated chapter subtitle",
                            url=url,
                            page_number=page_number,
                            page_total=page_total,
                            selector="p#chapter-subtitle[contenteditable]",
                            details=(
                                "After applying the translated HTML, replace the editable "
                                "chapter subtitle and commit its input/change events before Save."
                            ),
                            text_to_copy=translated_subtitle,
                        )
                        page.wait_for_selector(
                            'p#chapter-subtitle[contenteditable]',
                            timeout=10000,
                            state="visible",
                        )
                        self._set_chapter_subtitle(page, translated_subtitle)

                    self._request_action(
                        step_callback,
                        action='Click "Save" and wait five seconds',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=save_selector,
                        details=(
                            "Save this chapter. The next action will verify the persisted "
                            "HTML, title, and optional subtitle."
                        ),
                    )
                    page.wait_for_selector(save_selector, timeout=10000, state="visible")
                    page.click(save_selector)
                    page.wait_for_timeout(5000)

                    self._request_action(
                        step_callback,
                        action="Reload the saved page for verification",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        details="Reload the same URL after Save before inspecting persisted content.",
                    )
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)

                    self._request_action(
                        step_callback,
                        action='Click "Edit" for save verification',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=edit_selector,
                        details="Reopen the chapter editor without changing content.",
                    )
                    page.wait_for_selector(edit_selector, timeout=20000, state="visible")
                    page.click(edit_selector)

                    self._request_action(
                        step_callback,
                        action='Click "Edit HTML" for save verification',
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=html_selector,
                        details="Reopen the saved raw HTML without changing content.",
                    )
                    page.wait_for_selector(html_selector, timeout=10000, state="visible")
                    page.click(html_selector)

                    self._request_action(
                        step_callback,
                        action="Compare the saved HTML, title, and subtitle",
                        url=url,
                        page_number=page_number,
                        page_total=page_total,
                        selector=f"{code_selector}, #chapter-title, #chapter-subtitle",
                        details=(
                            "Read the persisted values and compare them with the translated "
                            "HTML and chapter metadata. Injection stops on any mismatch."
                        ),
                    )
                    page.wait_for_selector(code_selector, timeout=10000, state="visible")
                    saved_html = page.evaluate(
                        'document.getElementById("code-box").innerText'
                    )
                    saved_title = self._read_chapter_title(page)
                    saved_subtitle = self._read_chapter_subtitle(page)

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
                        self._log_troubleshoot(
                            "Title verification mismatch: "
                            f"expected={translated_title!r}; saved={saved_title!r}"
                        )
                        raise RuntimeError(
                            f"Save verification failed for {url}: persisted title does not match. "
                            f"Expected {translated_title!r}; saved {saved_title!r}."
                        )
                    if (
                        translated_subtitle
                        and self._normalized_text(saved_subtitle)
                        != self._normalized_text(translated_subtitle)
                    ):
                        self._log_troubleshoot(
                            "Subtitle verification mismatch: "
                            f"expected={translated_subtitle!r}; saved={saved_subtitle!r}"
                        )
                        raise RuntimeError(
                            f"Save verification failed for {url}: persisted subtitle does not match. "
                            f"Expected {translated_subtitle!r}; saved {saved_subtitle!r}."
                        )
                    self._log_troubleshoot(
                        f"VERIFIED page {page_number}/{page_total}: saved HTML, title, "
                        "and optional subtitle match."
                    )
            except Exception as exc:
                self._log_troubleshoot(f"STOPPED: {type(exc).__name__}: {exc}")
                raise
            finally:
                context.close()
                browser.close()

        self.print_callback("Injection complete. Every page passed save verification.")
