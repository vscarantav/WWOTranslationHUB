import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from extractor import EdTechBookExtractor


class EdTechBookExtractorTests(unittest.TestCase):
    def _temporary_output(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def test_accepts_and_normalizes_an_edtech_book_url(self):
        with self._temporary_output() as output_dir:
            extractor = EdTechBookExtractor(
                " https://books.byui.edu/example_book/?unused=yes#chapter ",
                output_dir,
            )
        self.assertEqual(extractor.book_url, "https://books.byui.edu/example_book")

    def test_converts_editor_url_to_the_public_book_root(self):
        with self._temporary_output() as output_dir:
            extractor = EdTechBookExtractor(
                "https://books.byui.edu/editor/Math_108X_PT/chapter_id",
                output_dir,
            )

        self.assertEqual(
            extractor.book_url,
            "https://books.byui.edu/Math_108X_PT",
        )

    def test_rejects_non_edtech_urls(self):
        with self._temporary_output() as output_dir:
            with self.assertRaises(ValueError):
                EdTechBookExtractor("https://example.com/book", output_dir)

    def test_rejects_toc_links_outside_the_selected_book(self):
        with self._temporary_output() as output_dir:
            extractor = EdTechBookExtractor(
                "https://books.byui.edu/current_book",
                output_dir,
                print_callback=lambda _message: None,
            )
            self.assertEqual(
                extractor._resolve_chapter_url("lesson_one"),
                "https://books.byui.edu/current_book/lesson_one",
            )
            self.assertIsNone(
                extractor._resolve_chapter_url(
                    "https://books.byui.edu/different_book/lesson_one"
                )
            )

    def test_builds_ordered_filename_from_the_real_page_title(self):
        filename = EdTechBookExtractor._build_filename(
            2,
            15,
            "Lição 1: Preparar-se para o Sucesso",
            "https://books.byui.edu/current_book/lesson_one",
        )

        self.assertEqual(
            filename,
            "002_licao_1_preparar_se_para_o_sucesso.html",
        )

    def test_browser_context_allows_complete_codemirror_copy(self):
        with self._temporary_output() as output_dir:
            extractor = EdTechBookExtractor(
                "https://books.byui.edu/current_book", output_dir
            )
            playwright = MagicMock()
            browser = playwright.chromium.launch.return_value
            context = browser.new_context.return_value

            actual_browser, actual_context = extractor._launch_anonymous_context(
                playwright
            )

            playwright.chromium.launch.assert_called_once_with(headless=False)
            browser.new_context.assert_called_once_with(
                no_viewport=True,
                permissions=["clipboard-read", "clipboard-write"],
            )
            context.clear_cookies.assert_called_once_with()
            self.assertIs(actual_browser, browser)
            self.assertIs(actual_context, context)

    def test_extraction_uses_the_visible_edit_chapter_link(self):
        with self._temporary_output() as output_dir:
            extractor = EdTechBookExtractor(
                "https://books.byui.edu/current_book", output_dir
            )
            extractor._prepare_output()
            page = MagicMock()
            html_button = MagicMock()
            html_source = MagicMock()
            html_source.inner_text.return_value = "<p>Visible partial</p>"
            page.get_by_role.return_value = html_button
            page.locator.return_value = html_source
            complete_html = (
                "<p>Visible partial</p>"
                "<section><p>Complete virtualized remainder</p></section>"
            )

            def evaluate(script, *args):
                if "chapter-title" in script:
                    return ""
                if "chapter-subtitle" in script:
                    return "Subtitle"
                if "navigator.clipboard.readText" in script:
                    return complete_html
                return None

            page.evaluate.side_effect = evaluate
            result = extractor._extract_chapter(
                page,
                "https://books.byui.edu/current_book/lesson_one",
                1,
                toc_title="Title & Overview",
                filename="002_title_overview.html",
            )

            html = (
                Path(output_dir) / "raw_html" / "002_title_overview.html"
            ).read_text(encoding="utf-8")
            self.assertIn("Title &amp; Overview", html)
            self.assertIn(complete_html, html)
            self.assertNotEqual(html_source.inner_text.return_value, complete_html)
            self.assertEqual(result["toc_scope"], "all_chapters")
            self.assertEqual(result["filename"], "002_title_overview.html")
            self.assertEqual(
                result["local_path"],
                "raw_html/002_title_overview.html",
            )
            page.fill.assert_not_called()
            self.assertIn('a.btn-edit[aria-label="Edit chapter"]', extractor.EDIT_SELECTOR)
            self.assertIn('[href^="/editor/"]', extractor.EDIT_SELECTOR)
            page.get_by_role.assert_called_once_with(
                "button", name="HTML", exact=True
            )
            html_button.click.assert_called_once_with()
            page.locator.assert_called_once_with(extractor.HTML_SOURCE_SELECTOR)
            html_source.inner_text.assert_called_once_with()
            self.assertEqual(page.wait_for_function.call_count, 2)
            self.assertEqual(
                page.wait_for_function.call_args_list[0].kwargs["arg"],
                extractor.HTML_SOURCE_SELECTOR,
            )
            self.assertEqual(
                page.wait_for_function.call_args_list[0].kwargs["timeout"],
                10_000,
            )
            self.assertEqual(
                page.wait_for_function.call_args_list[1].kwargs["timeout"],
                10_000,
            )
            html_source.click.assert_called_once_with()
            self.assertEqual(
                [call.args[0] for call in html_source.press.call_args_list],
                ["Control+A", "Control+C"],
            )
            self.assertFalse(any(
                call.args and call.args[0] == "#chapter-title"
                for call in page.wait_for_selector.call_args_list
            ))
            page.click.assert_called_once_with(extractor.EDIT_SELECTOR)
            page.wait_for_url.assert_called_once_with(
                "**/editor/**", timeout=60_000, wait_until="domcontentloaded"
            )

            extractor._write_mapping([result])
            link_mapping = __import__("json").loads(
                (Path(output_dir) / "link_mapping.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                link_mapping["url_to_local_file"][result["url"]],
                "raw_html/002_title_overview.html",
            )
            self.assertEqual(
                link_mapping["path_to_local_file"]["/current_book/lesson_one"],
                "raw_html/002_title_overview.html",
            )


if __name__ == "__main__":
    unittest.main()
