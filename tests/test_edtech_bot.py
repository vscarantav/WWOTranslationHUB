import shutil
import json
import re
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.edtech_bot import EdTechScraperBot
from controller import TranslationController
from main_ui import (
    generate_edtech_excel_report,
    get_edtech_report_name,
    validate_edtech_shell_details,
)


class EdTechAnonymousBrowserTests(unittest.TestCase):
    def test_launches_non_persistent_context_and_clears_cookies(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            log = Mock()
            bot = EdTechScraperBot(
                "https://books.byui.edu/example",
                "PTBR",
                str(workspace),
                print_callback=log,
            )
            playwright = Mock()
            browser = playwright.chromium.launch.return_value
            context = browser.new_context.return_value

            actual_browser, actual_context = bot._launch_anonymous_context(playwright)

            playwright.chromium.launch.assert_called_once_with(headless=False)
            browser.new_context.assert_called_once_with(no_viewport=True)
            context.clear_cookies.assert_called_once_with()
            self.assertIs(actual_browser, browser)
            self.assertIs(actual_context, context)
            self.assertIn("fresh anonymous browser session", log.call_args.args[0])
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_rejects_lesson_urls_from_another_book(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            log = Mock()
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=log,
            )

            self.assertEqual(
                bot._resolve_lesson_url("lesson_one"),
                "https://books.byui.edu/current_book/lesson_one",
            )
            self.assertIsNone(
                bot._resolve_lesson_url(
                    "https://books.byui.edu/different_book/copied_page"
                )
            )
            self.assertTrue(any(
                "REJECTED" in call.args[0]
                for call in log.call_args_list
            ))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_removes_stale_translation_output_before_a_new_run(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        translated_dir = workspace / "raw_html_PTBR"
        translated_dir.mkdir(parents=True)
        (translated_dir / "lesson_1.html").write_text("old book", encoding="utf-8")
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )

            bot.reset_translation_output()

            self.assertFalse(translated_dir.exists())
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_loads_only_complete_same_book_translation_for_resume(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        raw_dir = workspace / "raw_html"
        translated_dir = workspace / "raw_html_PTBR"
        raw_dir.mkdir(parents=True)
        translated_dir.mkdir(parents=True)
        raw_path = raw_dir / "lesson_1.html"
        translated_path = translated_dir / "lesson_1.html"
        raw_path.write_text(
            '<div id="edtech-meta-title">English title</div><p>English text</p>',
            encoding="utf-8",
        )
        translated_path.write_text(
            '<div id="edtech-meta-title">Título</div><p>Texto traduzido</p>',
            encoding="utf-8",
        )
        mapping = [{
            "url": "https://books.byui.edu/current_book/lesson_one",
            "filename": "lesson_1.html",
            "source_title": "English title",
            "source_subtitle": "",
            "toc_scope": "all_chapters",
            "raw_filepath": "stale/path.html",
            "translated_filepath": "stale/translated.html",
        }]
        (workspace / "edtech_mapping.json").write_text(
            json.dumps(mapping),
            encoding="utf-8",
        )
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )

            resumable = bot.load_resumable_injection()

            self.assertEqual(len(resumable), 1)
            self.assertEqual(resumable[0]["raw_filepath"], str(raw_path))
            self.assertEqual(resumable[0]["translated_filepath"], str(translated_path))

            legacy_mapping = [dict(mapping[0])]
            legacy_mapping[0].pop("source_subtitle")
            (workspace / "edtech_mapping.json").write_text(
                json.dumps(legacy_mapping),
                encoding="utf-8",
            )
            self.assertEqual(bot.load_resumable_injection(), [])

            (workspace / "edtech_mapping.json").write_text(
                json.dumps(mapping),
                encoding="utf-8",
            )

            leaf_only_mapping = [dict(mapping[0])]
            leaf_only_mapping[0].pop("toc_scope")
            (workspace / "edtech_mapping.json").write_text(
                json.dumps(leaf_only_mapping),
                encoding="utf-8",
            )
            self.assertEqual(bot.load_resumable_injection(), [])

            (workspace / "edtech_mapping.json").write_text(
                json.dumps(mapping),
                encoding="utf-8",
            )

            bot.book_url = "https://books.byui.edu/different_book"
            self.assertEqual(bot.load_resumable_injection(), [])
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_toc_selector_includes_parent_and_leaf_chapter_pages(self):
        toc = BeautifulSoup(
            '''<div id="toc">
                <div class="toc-row" data-entity-type="chapter" data-children="2,3">
                    <a class="btn text-start" href="/book/parent">Parent chapter</a>
                </div>
                <div class="toc-row" data-entity-type="chapter" data-children="">
                    <a class="btn text-start" href="/book/leaf">Leaf lesson</a>
                </div>
            </div>''',
            "html.parser",
        )

        hrefs = [
            link["href"]
            for link in toc.select(EdTechScraperBot.TOC_CHAPTER_LINK_SELECTOR)
        ]

        self.assertEqual(hrefs, ["/book/parent", "/book/leaf"])

    def test_injection_action_waits_for_callback_approval(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            callback = Mock(return_value=True)

            bot._request_action(
                callback,
                action='Click "Save"',
                url="https://books.byui.edu/current_book/lesson_one",
                page_number=1,
                page_total=2,
                selector='button[data-ribbon-action="Save"]',
                details="Save this page.",
                text_to_copy="translated text",
            )

            callback.assert_called_once()
            payload = callback.call_args.args[0]
            self.assertEqual(payload["action"], 'Click "Save"')
            self.assertEqual(payload["text_to_copy"], "translated text")
            self.assertEqual(payload["page_number"], 1)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_google_login_click_uses_a_guarded_non_waiting_dom_click(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            log = Mock()
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=log,
            )
            page = MagicMock()
            page.evaluate.return_value = True

            bot._start_google_login(
                page,
                'button[data-action="LoginGoogle"]',
                'button#user-link[data-bs-toggle="dropdown"]',
            )

            script, selector = page.evaluate.call_args.args
            self.assertIn("if (!button) return false", script)
            self.assertEqual(selector, 'button[data-action="LoginGoogle"]')
            page.click.assert_not_called()
            self.assertTrue(any(
                "without waiting on its same-tab OAuth navigation" in call.args[0]
                for call in log.call_args_list
            ))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_google_login_treats_navigation_destroying_context_as_started(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            log = Mock()
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=log,
            )
            page = MagicMock()
            page.evaluate.side_effect = RuntimeError("Execution context was destroyed")
            page.url = "https://accounts.google.com/o/oauth2/v2/auth"

            bot._start_google_login(
                page,
                'button[data-action="LoginGoogle"]',
                'button#user-link[data-bs-toggle="dropdown"]',
            )

            self.assertTrue(any(
                "Google SSO navigation started" in call.args[0]
                for call in log.call_args_list
            ))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_google_login_reports_a_disappeared_button_without_null_click(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            page = MagicMock()
            page.evaluate.return_value = False
            page.url = "https://books.byui.edu"
            page.locator.return_value.is_visible.return_value = False

            with self.assertRaisesRegex(RuntimeError, "disappeared"):
                bot._start_google_login(
                    page,
                    'button[data-action="LoginGoogle"]',
                    'button#user-link[data-bs-toggle="dropdown"]',
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_login_finishes_before_controlled_injection_actions_begin(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            bot._request_action = Mock()
            page = MagicMock()
            page.locator.return_value.is_visible.return_value = True
            page.evaluate.return_value = True

            with patch("bots.edtech_bot.time.sleep"):
                bot._ensure_login(page)

            bot._request_action.assert_not_called()
            page.goto.assert_called_once_with(bot.base_url, timeout=60000)
            page.click.assert_called_once_with(
                'button#user-link[data-target-template="modal-login"]'
            )
            page.wait_for_selector.assert_any_call(
                'button#user-link[data-bs-toggle="dropdown"]',
                timeout=180000,
                state="visible",
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_injection_verifies_saved_content_before_completing(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        translated_dir = workspace / "raw_html_PTBR"
        translated_dir.mkdir(parents=True)
        translated_file = translated_dir / "lesson_1.html"
        translated_file.write_text(
            '<div id="edtech-meta-title">Título traduzido</div>'
            '<div id="edtech-meta-subtitle">Carta de Agradecimento</div>'
            '<p>Texto traduzido</p>',
            encoding="utf-8",
        )
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            page = MagicMock()
            login_locator = MagicMock()
            login_locator.is_visible.return_value = False
            logged_in_locator = MagicMock()
            logged_in_locator.is_visible.return_value = True
            editable_locator = MagicMock()

            def locator(selector):
                if selector == 'button#user-link[data-target-template="modal-login"]':
                    return login_locator
                if selector == 'button#user-link[data-bs-toggle="dropdown"]':
                    return logged_in_locator
                return editable_locator

            page.locator.side_effect = locator

            def evaluate(script, *args):
                if not args and 'document.getElementById("code-box").innerText' in script:
                    return "<p>Texto traduzido</p>"
                if not args and 'document.getElementById("chapter-title")' in script:
                    return "Título traduzido"
                if not args and 'document.getElementById("chapter-subtitle")' in script:
                    return "Carta de Agradecimento"
                return None

            page.evaluate.side_effect = evaluate
            playwright = MagicMock()
            browser = playwright.chromium.launch.return_value
            context = browser.new_context.return_value
            context.new_page.return_value = page
            manager = MagicMock()
            manager.__enter__.return_value = playwright
            actions = []

            with (
                patch("bots.edtech_bot.sync_playwright", return_value=manager),
                patch("bots.edtech_bot.time.sleep"),
            ):
                bot.run_injection(
                    extracted_files=[{
                        "url": "https://books.byui.edu/current_book/lesson_one",
                        "filename": "lesson_1.html",
                        "source_title": "English title",
                        "source_subtitle": "Letter of Appreciation",
                        "translated_filepath": str(translated_file),
                    }],
                    step_callback=lambda payload: actions.append(payload) or True,
                )

            action_names = [action["action"] for action in actions]
            self.assertNotIn("Open EdTech for the login check", action_names)
            self.assertIn('Click "Save" and wait five seconds', action_names)
            self.assertIn("Reload the saved page for verification", action_names)
            self.assertIn("Compare the saved HTML, title, and subtitle", action_names)
            self.assertLess(
                action_names.index("Copy translated HTML into the code box"),
                action_names.index("Copy the translated chapter title"),
            )
            self.assertLess(
                action_names.index("Copy the translated chapter title"),
                action_names.index("Copy the translated chapter subtitle"),
            )
            self.assertLess(
                action_names.index("Copy the translated chapter subtitle"),
                action_names.index('Click "Save" and wait five seconds'),
            )
            self.assertEqual(
                actions[action_names.index("Copy translated HTML into the code box")]["text_to_copy"],
                "<p>Texto traduzido</p>",
            )
            self.assertGreaterEqual(page.goto.call_count, 3)
            page.locator.assert_any_call("#chapter-title")
            page.locator.assert_any_call("#chapter-subtitle")
            editable_locator.fill.assert_any_call("Título traduzido")
            editable_locator.fill.assert_any_call("Carta de Agradecimento")
            context.close.assert_called_once_with()
            browser.close.assert_called_once_with()
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_reads_title_from_the_editable_chapter_heading(self):
        page = MagicMock()
        page.evaluate.return_value = "Academic Honesty, Ethics and Integrity"

        title = EdTechScraperBot._read_chapter_title(page)

        self.assertEqual(title, "Academic Honesty, Ethics and Integrity")
        script = page.evaluate.call_args.args[0]
        self.assertIn('document.getElementById("chapter-title")', script)

    def test_reads_subtitle_from_the_optional_editable_chapter_paragraph(self):
        page = MagicMock()
        page.evaluate.return_value = "Letter of Appreciation"

        subtitle = EdTechScraperBot._read_chapter_subtitle(page)

        self.assertEqual(subtitle, "Letter of Appreciation")
        script = page.evaluate.call_args.args[0]
        self.assertIn('document.getElementById("chapter-subtitle")', script)

    def test_translated_title_carrier_decodes_html_entities_before_injection(self):
        title_html = "Ética &amp; Integridade"

        title = EdTechScraperBot._normalized_text(
            BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
        )

        self.assertEqual(title, "Ética & Integridade")

    def test_injection_removes_fragment_markers_and_repairs_strong_spacing(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            translated = (
                '<li>StartFragment<strong>Objetivo:</strong>\n'
                'Praticar a elaboração de prompts.EndFragment</li>'
                '<li><strong>Tamanho</strong>\n: Duas respostas</li>'
            )

            cleaned = bot._clean_translated_html_for_injection(translated)

            self.assertNotIn("StartFragment", cleaned)
            self.assertNotIn("EndFragment", cleaned)
            self.assertIn("</strong> Praticar", cleaned)
            self.assertIn("</strong>: Duas", cleaned)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_save_verification_accepts_benign_html_normalization(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            expected = (
                '<p class="message">Olá <strong>mundo</strong>.</p>'
                '<a href="/current_book/resource">Recurso</a>'
            )
            saved = (
                '<p class="message">\n  Olá <strong>mundo</strong>.\n</p>'
                '<a href="https://books.byui.edu/current_book/resource">Recurso</a>'
            )

            bot._verify_saved_html(
                {"filename": "lesson_1.html"},
                "https://books.byui.edu/current_book/lesson_one",
                expected,
                saved,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_save_verification_writes_snapshots_for_real_content_mismatch(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )

            with self.assertRaisesRegex(RuntimeError, "visible text mismatch"):
                bot._verify_saved_html(
                    {"filename": "lesson_1.html"},
                    "https://books.byui.edu/current_book/lesson_one",
                    "<p>Texto traduzido</p>",
                    "<p>Old English text</p>",
                )

            snapshot_dir = workspace / "verification_failures"
            self.assertEqual(
                (snapshot_dir / "lesson_1_expected.html").read_text(encoding="utf-8"),
                "<p>Texto traduzido</p>",
            )
            self.assertEqual(
                (snapshot_dir / "lesson_1_saved.html").read_text(encoding="utf-8"),
                "<p>Old English text</p>",
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class EdTechPreTranslationChecklistTests(unittest.TestCase):
    def test_accepts_confirmed_books_shell_and_normalizes_trailing_slash(self):
        shell_url, error = validate_edtech_shell_details(
            "yes",
            " https://books.byui.edu/example_pt/ ",
            "PT",
        )

        self.assertEqual(shell_url, "https://books.byui.edu/example_pt")
        self.assertIsNone(error)

    def test_blocks_translation_when_shell_has_not_been_created(self):
        shell_url, error = validate_edtech_shell_details(
            "no",
            "https://books.byui.edu/example_pt",
            "PT",
        )

        self.assertIsNone(shell_url)
        self.assertIn("Create the new PT book shell", error)

    def test_rejects_non_edtech_url(self):
        shell_url, error = validate_edtech_shell_details(
            "yes",
            "https://example.com/example_pt",
            "PT",
        )

        self.assertIsNone(shell_url)
        self.assertIn("books.byui.edu", error)


class EdTechExcelReportTests(unittest.TestCase):
    def test_controller_uses_embedded_edtech_chapter_title_for_report(self):
        controller = object.__new__(TranslationController)

        title = controller._extract_page_title(
            '<div id="edtech-meta-title" style="display:none;">Academic Honesty</div>'
            '<h2>Welcome</h2>',
            "html",
        )

        self.assertEqual(title, "Academic Honesty")

    def test_builds_book_specific_report_name(self):
        self.assertEqual(
            get_edtech_report_name(
                "https://books.byui.edu/writing_in_professional_contexts_pt"
            ),
            "Writing In Professional Contexts Pt EdTech Master",
        )

    def test_generates_standard_dashboard_with_edtech_identity(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            first_page = workspace / "lesson_1.html"
            second_page = workspace / "lesson_2.html"
            first_page.write_text(
                '<div id="edtech-meta-title">Introduction</div><p>First</p>',
                encoding="utf-8",
            )
            second_page.write_text(
                '<div id="edtech-meta-title">Planning Your Project</div><p>Second</p>',
                encoding="utf-8",
            )
            controller = Mock()
            controller._extract_page_title.side_effect = (
                lambda content, _ext: re.search(
                    r'<div id="edtech-meta-title">(.*?)</div>', content
                ).group(1)
            )
            controller.update_excel_dashboard.return_value = "report.xlsx"

            report_path = generate_edtech_excel_report(
                controller,
                "https://books.byui.edu/web_frontend_development_ii",
                "SPA",
                [
                    {"filename": "lesson_1.html", "raw_filepath": str(first_page)},
                    {"filename": "lesson_2.html", "raw_filepath": str(second_page)},
                ],
            )

            self.assertEqual(report_path, "report.xlsx")
            controller.update_excel_dashboard.assert_called_once_with(
                report_name="Web Frontend Development Ii EdTech Master",
                report_code="EDTECH-SPA",
                review_pages=[
                    {"title": "Introduction", "filepath": str(first_page)},
                    {"title": "Planning Your Project", "filepath": str(second_page)},
                ],
                excluded_sheets=("Dashboard", "Bot Analysis", "Raw Logs"),
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
