"""Read-only EdTech book HTML extractor.

This module intentionally contains no translation, AI, or book-update code.
It uses Google SSO and EdTech's CodeMirror HTML view, then writes each
chapter's complete source HTML to disk.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from html import escape
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.sync_api import Page, Playwright, sync_playwright


class EdTechBookExtractor:
    """Extract every chapter from a books.byui.edu book without saving changes."""

    BASE_URL = "https://books.byui.edu"
    TOC_CHAPTER_LINK_SELECTOR = (
        'div#toc > div.toc-row[data-entity-type="chapter"] > a.btn.text-start'
    )
    LOGIN_SELECTOR = 'button#user-link[data-target-template="modal-login"]'
    LOGGED_IN_SELECTOR = 'button#user-link[data-bs-toggle="dropdown"]'
    # The book page contains unrelated inline editor buttons. The chapter
    # editor is opened by this visible link to /editor/<book>/<chapter>.
    EDIT_SELECTOR = 'a.btn-edit[aria-label="Edit chapter"][href^="/editor/"]:visible'
    HTML_SOURCE_SELECTOR = (
        'div.cm-content[role="textbox"]'
        '[aria-label="Document HTML source"]'
        '[data-language="html"]'
    )

    def __init__(
        self,
        book_url: str,
        output_dir: Path | str,
        print_callback: Callable[[str], None] = print,
    ) -> None:
        self.book_url = self._validate_book_url(book_url)
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.raw_dir = self.output_dir / "raw_html"
        self.mapping_path = self.output_dir / "edtech_mapping.json"
        self.link_mapping_path = self.output_dir / "link_mapping.json"
        self.print = print_callback

    @staticmethod
    def _validate_book_url(book_url: str) -> str:
        value = (book_url or "").strip().rstrip("/")
        parsed = urlparse(value)
        path_parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() != "books.byui.edu"
            or not path_parts
        ):
            raise ValueError(
                "Book URL must be an HTTPS books.byui.edu book URL, for example "
                "https://books.byui.edu/example_book"
            )

        # Users may paste the redesigned editor route. Extraction must begin at
        # the public book root because that is where the complete TOC lives.
        if path_parts[0].casefold() == "editor":
            if len(path_parts) < 2:
                raise ValueError(
                    "Editor URL is missing a book name; expected "
                    "https://books.byui.edu/editor/example_book"
                )
            book_name = path_parts[1]
        else:
            book_name = path_parts[0]
        return urlunparse(
            (parsed.scheme, parsed.netloc, f"/{book_name}", "", "", "")
        )

    @staticmethod
    def _normalized_text(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def _is_url_in_book(self, candidate_url: str) -> bool:
        book = urlparse(self.book_url)
        candidate = urlparse(candidate_url)
        book_parts = [part for part in book.path.split("/") if part]
        candidate_parts = [part for part in candidate.path.split("/") if part]
        return bool(
            book_parts
            and candidate_parts
            and candidate.scheme in {"http", "https"}
            and candidate.hostname == book.hostname
            and candidate_parts[0] == book_parts[0]
        )

    def _resolve_chapter_url(self, href: str) -> str | None:
        candidate = urljoin(f"{self.book_url}/", href)
        parsed = urlparse(candidate)
        candidate = urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, "")
        )
        if not self._is_url_in_book(candidate):
            self.print(f"Ignoring a TOC link outside the selected book: {candidate}")
            return None
        return candidate

    def _prepare_output(self) -> None:
        """Clear only artifacts owned by this extractor from an earlier run."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        # Title-based filenames cannot be identified safely by a broad glob.
        # Use the previous manifest to remove only files created by this tool.
        owned_filenames: set[str] = set()
        if self.mapping_path.is_file():
            try:
                prior_records = json.loads(
                    self.mapping_path.read_text(encoding="utf-8")
                )
                if isinstance(prior_records, list):
                    for record in prior_records:
                        if isinstance(record, dict):
                            filename = record.get("filename", "")
                            if (
                                isinstance(filename, str)
                                and Path(filename).name == filename
                                and filename.lower().endswith(".html")
                            ):
                                owned_filenames.add(filename)
            except (OSError, json.JSONDecodeError):
                pass

        for path in self.raw_dir.iterdir():
            is_legacy_file = bool(
                re.fullmatch(r"lesson_\d+\.html", path.name, flags=re.IGNORECASE)
            )
            if path.is_file() and (path.name in owned_filenames or is_legacy_file):
                path.unlink()
        if self.mapping_path.is_file():
            self.mapping_path.unlink()
        if self.link_mapping_path.is_file():
            self.link_mapping_path.unlink()

    @staticmethod
    def _build_filename(
        number: int,
        total: int,
        title: str,
        url: str,
    ) -> str:
        """Create a sortable, portable filename from the actual TOC title."""
        source_name = title.strip() or urlparse(url).path.rstrip("/").split("/")[-1]
        ascii_name = (
            unicodedata.normalize("NFKD", source_name)
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        slug = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")
        slug = slug[:120].rstrip("_") or f"page_{number}"
        width = max(3, len(str(total)))
        return f"{number:0{width}d}_{slug}.html"

    def _launch_anonymous_context(self, playwright: Playwright):
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            no_viewport=True,
            permissions=["clipboard-read", "clipboard-write"],
        )
        context.clear_cookies()
        self.print(
            "Opened a fresh browser session. Complete Google SSO if EdTech asks you to log in."
        )
        return browser, context

    def _google_login_transition_started(self, page: Page) -> bool:
        try:
            current_host = (urlparse(page.url or "").hostname or "").lower()
        except Exception:
            current_host = ""
        if current_host and current_host != "books.byui.edu":
            return True
        try:
            return page.locator(self.LOGGED_IN_SELECTOR).is_visible()
        except Exception:
            return False

    def _start_google_login(self, page: Page) -> None:
        google_button = 'button[data-action="LoginGoogle"]'
        try:
            clicked = page.evaluate(
                """(selector) => {
                    const button = document.querySelector(selector);
                    if (!button) return false;
                    button.click();
                    return true;
                }""",
                google_button,
            )
        except Exception as error:
            if self._google_login_transition_started(page):
                return
            raise RuntimeError(f"Could not start Google SSO: {error}") from error
        if not clicked and not self._google_login_transition_started(page):
            raise RuntimeError(
                "The Google Login button disappeared before it could be clicked."
            )

    def _ensure_login(self, page: Page) -> None:
        self.print(f"Checking EdTech login at {self.BASE_URL}...")
        page.goto(self.BASE_URL, timeout=60_000, wait_until="domcontentloaded")
        time.sleep(3)
        page.wait_for_selector(
            f"{self.LOGIN_SELECTOR}, {self.LOGGED_IN_SELECTOR}",
            timeout=30_000,
            state="visible",
        )

        if page.locator(self.LOGIN_SELECTOR).is_visible():
            page.click(self.LOGIN_SELECTOR)
            google_button = 'button[data-action="LoginGoogle"]'
            page.wait_for_selector(google_button, timeout=5_000, state="visible")
            self._start_google_login(page)
            self.print("Waiting up to three minutes for Google SSO to finish...")
            page.wait_for_selector(
                self.LOGGED_IN_SELECTOR,
                timeout=180_000,
                state="visible",
            )
            time.sleep(3)
            self.print("Login confirmed.")
        elif page.locator(self.LOGGED_IN_SELECTOR).is_visible():
            self.print("Already logged in.")
        else:
            raise RuntimeError("EdTech login state could not be determined.")

    def _discover_chapters(self, page: Page) -> list[dict[str, str]]:
        self.print(f"Opening book: {self.book_url}")
        page.goto(self.book_url, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_selector("div#toc", timeout=60_000)
        page.wait_for_selector(
            self.TOC_CHAPTER_LINK_SELECTOR,
            timeout=20_000,
            state="attached",
        )

        links = page.locator(self.TOC_CHAPTER_LINK_SELECTOR)
        chapters: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for index in range(links.count()):
            link = links.nth(index)
            href = link.get_attribute("href")
            chapter_url = self._resolve_chapter_url(href) if href else None
            if chapter_url and chapter_url not in seen_urls:
                seen_urls.add(chapter_url)
                chapters.append(
                    {
                        "url": chapter_url,
                        "title": self._normalized_text(link.inner_text()),
                    }
                )
        if not chapters:
            raise RuntimeError("The book table of contents contained no chapter pages.")
        self.print(f"Found {len(chapters)} chapter page(s).")
        return chapters

    @staticmethod
    def _read_chapter_title(page: Page) -> str:
        return page.evaluate(
            """() => {
                const el = document.getElementById("chapter-title");
                if (!el) return "";
                if ("value" in el && el.value) return el.value;
                return el.innerText || el.textContent || "";
            }"""
        )

    @staticmethod
    def _read_chapter_subtitle(page: Page) -> str:
        return page.evaluate(
            """() => {
                const el = document.getElementById("chapter-subtitle");
                if (!el) return "";
                if ("value" in el && el.value) return el.value;
                return el.innerText || el.textContent || "";
            }"""
        )

    def _extract_chapter(
        self,
        page: Page,
        url: str,
        number: int,
        toc_title: str = "",
        filename: str | None = None,
    ) -> dict[str, str]:
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")

        # The redesigned /editor page no longer contains #chapter-title. Read
        # optional metadata from the public chapter page, with the TOC title as
        # the reliable fallback, before following the editor link.
        try:
            page_title = self._normalized_text(self._read_chapter_title(page))
        except Exception:
            page_title = ""
        title = page_title or self._normalized_text(toc_title)
        try:
            subtitle = self._normalized_text(self._read_chapter_subtitle(page))
        except Exception:
            subtitle = ""

        # This link opens EdTech's chapter editor. The script only reads from
        # it; it never fills an editable field or invokes Apply or Save.
        page.wait_for_selector(self.EDIT_SELECTOR, timeout=10_000, state="visible")
        self.print("  Clicking the Edit chapter link...")
        page.click(self.EDIT_SELECTOR)
        page.wait_for_url(
            "**/editor/**",
            timeout=60_000,
            wait_until="domcontentloaded",
        )
        self.print(f"  Editor opened: {page.url}")

        html_button = page.get_by_role("button", name="HTML", exact=True)
        html_button.wait_for(timeout=10_000, state="visible")
        self.print("  Clicking the HTML view button...")
        html_button.click()

        html_source = page.locator(self.HTML_SOURCE_SELECTOR)
        html_source.wait_for(timeout=10_000, state="visible")
        page.wait_for_function(
            """(selector) => {
                const source = document.querySelector(selector);
                return Boolean(source && source.innerText.trim().length);
            }""",
            arg=self.HTML_SOURCE_SELECTOR,
            timeout=10_000,
        )
        # CodeMirror virtualizes long documents, so innerText contains only the
        # lines currently rendered in the viewport. Select All + Copy invokes
        # CodeMirror's clipboard handler, which returns its complete document.
        visible_html = html_source.inner_text()
        page.evaluate("() => navigator.clipboard.writeText('')")
        html_source.click()
        html_source.press("Control+A")
        html_source.press("Control+C")
        page.wait_for_function(
            """async () => {
                const text = await navigator.clipboard.readText();
                return Boolean(text && text.trim().length);
            }""",
            timeout=10_000,
        )
        body_html = page.evaluate("() => navigator.clipboard.readText()")
        if not body_html or not body_html.strip():
            raise RuntimeError(
                "CodeMirror did not copy any HTML to the clipboard"
            )
        if len(body_html) < len(visible_html):
            raise RuntimeError(
                "the copied HTML was shorter than CodeMirror's visible DOM; "
                "refusing to save an incomplete page"
            )
        self.print(
            f"  Copied {len(body_html)} HTML character(s) from CodeMirror "
            f"(visible DOM: {len(visible_html)})."
        )

        metadata_parts = []
        if title:
            metadata_parts.append(
                '<div id="edtech-meta-title" style="display:none;">'
                f"{escape(title, quote=False)}</div>"
            )
        if subtitle:
            metadata_parts.append(
                '<div id="edtech-meta-subtitle" style="display:none;">'
                f"{escape(subtitle, quote=False)}</div>"
            )

        filename = filename or self._build_filename(number, number, title, url)
        filepath = self.raw_dir / filename
        metadata = "\n".join(metadata_parts)
        output_html = f"{metadata}\n{body_html}" if metadata else body_html
        filepath.write_text(output_html, encoding="utf-8")
        return {
            "url": url,
            "filename": filename,
            "source_title": title,
            "source_subtitle": subtitle,
            "toc_scope": "all_chapters",
            "local_path": f"raw_html/{filename}",
            "raw_filepath": str(filepath),
        }

    def _write_mapping(self, records: list[dict[str, str]]) -> None:
        self.mapping_path.write_text(
            json.dumps(records, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        link_mapping = {
            "book_url": self.book_url,
            "url_to_local_file": {
                record["url"]: record["local_path"]
                for record in records
            },
            "path_to_local_file": {
                urlparse(record["url"]).path: record["local_path"]
                for record in records
            },
        }
        self.link_mapping_path.write_text(
            json.dumps(link_mapping, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )

    def run(self) -> list[dict[str, str]]:
        """Extract all chapters, continuing through the TOC after failures."""
        self._prepare_output()
        records: list[dict[str, str]] = []
        failures: list[str] = []

        with sync_playwright() as playwright:
            browser, context = self._launch_anonymous_context(playwright)
            try:
                page = context.new_page()
                self._ensure_login(page)
                chapters = self._discover_chapters(page)
                for number, chapter in enumerate(chapters, start=1):
                    url = chapter["url"]
                    self.print(f"Extracting [{number}/{len(chapters)}]: {url}")
                    try:
                        record = self._extract_chapter(
                            page,
                            url,
                            number,
                            toc_title=chapter["title"],
                            filename=self._build_filename(
                                number,
                                len(chapters),
                                chapter["title"],
                                url,
                            ),
                        )
                        records.append(record)
                        self._write_mapping(records)
                    except Exception as error:
                        failures.append(f"{url}: {error}")
                        self.print(f"FAILED [{number}/{len(chapters)}]: {error}")
                        if page.is_closed():
                            self.print("Browser was closed; stopping extraction.")
                            break
            finally:
                context.close()
                browser.close()

        self._write_mapping(records)
        if failures:
            details = "\n".join(f"- {failure}" for failure in failures)
            raise RuntimeError(
                f"Extracted {len(records)} page(s), but {len(failures)} page(s) failed:\n{details}"
            )
        self.print(f"Done. Saved {len(records)} HTML page(s) in {self.raw_dir}")
        self.print(f"Mapping: {self.mapping_path}")
        self.print(f"Link mapping: {self.link_mapping_path}")
        return records


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract every EdTech book chapter to HTML without editing the book."
    )
    parser.add_argument(
        "book_url",
        nargs="?",
        help="EdTech book URL, such as https://books.byui.edu/example_book",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="Output directory (default: the output folder beside this script)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    book_url = args.book_url or input("EdTech book URL: ").strip()
    try:
        EdTechBookExtractor(book_url, args.output_dir).run()
    except (ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nExtraction cancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
