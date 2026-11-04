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
    translate_edtech_files_and_generate_report,
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
            browser.new_context.assert_called_once_with(
                no_viewport=True,
                permissions=["clipboard-read", "clipboard-write"],
            )
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

            failed_raw_path = raw_dir / "lesson_2.html"
            failed_translated_path = translated_dir / "lesson_2.html"
            failed_html = (
                '<div id="edtech-meta-title">Failed English title</div>'
                '<p>Untranslated English text</p>'
            )
            failed_raw_path.write_text(failed_html, encoding="utf-8")
            failed_translated_path.write_text(failed_html, encoding="utf-8")
            partial_mapping = [
                mapping[0],
                {
                    "url": "https://books.byui.edu/current_book/lesson_two",
                    "filename": "lesson_2.html",
                    "source_title": "Failed English title",
                    "source_subtitle": "",
                    "toc_scope": "all_chapters",
                    "raw_filepath": "stale/path-2.html",
                    "translated_filepath": "stale/translated-2.html",
                },
            ]
            (workspace / "edtech_mapping.json").write_text(
                json.dumps(partial_mapping),
                encoding="utf-8",
            )
            partial_resume = bot.load_resumable_injection()
            self.assertEqual(
                [item["filename"] for item in partial_resume],
                ["lesson_1.html"],
            )

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

    def test_extraction_uses_visible_edit_link_and_complete_codemirror_html(self):
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
            html_source = MagicMock()
            html_source.inner_text.return_value = "<p>Visible partial</p>"
            complete_html = (
                "<p>Visible partial</p>"
                "<section><p>Complete virtualized remainder</p></section>"
            )

            bot._open_editor = Mock()
            bot._read_chapter_title = Mock(return_value="")
            bot._read_chapter_subtitle = Mock(return_value="Subtitle")
            bot._open_html_source = Mock(return_value=html_source)
            bot._copy_full_html_source = Mock(return_value=complete_html)
            bot._close_editor = Mock()

            result = bot._extract_chapter(
                page,
                "https://books.byui.edu/current_book/lesson_one",
                1,
                toc_title="Title & Overview",
            )

            extracted_html = Path(result["raw_filepath"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("Title &amp; Overview", extracted_html)
            self.assertIn(complete_html, extracted_html)
            self.assertIn(
                'a.btn-edit[aria-label="Edit chapter"]',
                bot.EDIT_SELECTOR,
            )
            self.assertIn('[href^="/editor/"]', bot.EDIT_SELECTOR)
            self.assertEqual(
                bot.SAVE_SELECTOR,
                'button.btn.bi-floppy2-fill:visible',
            )
            self.assertEqual(
                bot.CLOSE_SELECTOR,
                'button.btn.bi-x-lg.float-end:visible',
            )
            bot._open_editor.assert_called_once_with(page)
            bot._open_html_source.assert_called_once_with(page)
            bot._copy_full_html_source.assert_called_once_with(page, html_source)
            bot._close_editor.assert_called_once_with(
                page,
                "https://books.byui.edu/current_book/lesson_one",
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_current_editor_controls_open_edit_and_html_source(self):
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
            edit_button = MagicMock()
            html_button = MagicMock()
            html_source = MagicMock()

            def locator(selector):
                if selector == bot.EDIT_SELECTOR:
                    result = MagicMock()
                    result.first = edit_button
                    return result
                if selector == bot.HTML_SOURCE_SELECTOR:
                    return html_source
                raise AssertionError(f"Unexpected selector: {selector}")

            page.locator.side_effect = locator
            page.get_by_role.return_value = html_button

            bot._open_editor(page)
            actual_source = bot._open_html_source(page)

            self.assertIs(actual_source, html_source)
            edit_button.wait_for.assert_called_once_with(
                timeout=20000,
                state="visible",
            )
            edit_button.click.assert_called_once_with()
            page.wait_for_url.assert_called_once_with(
                "**/editor/**",
                timeout=60000,
                wait_until="domcontentloaded",
            )
            page.get_by_role.assert_called_once_with(
                "button",
                name="HTML",
                exact=True,
            )
            html_button.click.assert_called_once_with()
            html_source.wait_for.assert_called_once_with(
                timeout=10000,
                state="visible",
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_refreshes_stale_slug_from_live_toc_for_partial_resume(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        translated_dir = workspace / "raw_html_PTBR"
        translated_dir.mkdir(parents=True)
        translated_path = translated_dir / "lesson_2.html"
        translated_path.write_text(
            '<div id="edtech-meta-title">Título traduzido</div><p>Texto</p>',
            encoding="utf-8",
        )
        mapping = [
            {
                "url": "https://books.byui.edu/current_book/old-one",
                "filename": "lesson_1.html",
                "source_title": "First source title",
            },
            {
                "url": "https://books.byui.edu/current_book/old-two",
                "filename": "lesson_2.html",
                "source_title": "Second source title",
                "translated_filepath": str(translated_path),
            },
        ]
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
            bot._read_live_toc = Mock(return_value=[
                {
                    "url": "https://books.byui.edu/current_book/new-one",
                    "title": "First source title",
                },
                {
                    "url": "https://books.byui.edu/current_book/new-two",
                    "title": "Título traduzido",
                },
            ])

            refreshed = bot._refresh_injection_urls(MagicMock(), [mapping[1]])

            self.assertEqual(
                refreshed[0]["url"],
                "https://books.byui.edu/current_book/new-two",
            )
            saved_mapping = json.loads(
                (workspace / "edtech_mapping.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["url"] for item in saved_mapping],
                [
                    "https://books.byui.edu/current_book/new-one",
                    "https://books.byui.edu/current_book/new-two",
                ],
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_refuses_live_toc_remap_when_title_identity_changed(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            bot = EdTechScraperBot(
                "https://books.byui.edu/current_book",
                "PTBR",
                str(workspace),
                print_callback=Mock(),
            )
            bot._read_live_toc = Mock(return_value=[{
                "url": "https://books.byui.edu/current_book/unrelated",
                "title": "A different chapter",
            }])
            item = {
                "url": "https://books.byui.edu/current_book/old-one",
                "filename": "lesson_1.html",
                "source_title": "Expected chapter",
            }

            with self.assertRaisesRegex(RuntimeError, "TOC mismatch"):
                bot._refresh_injection_urls(MagicMock(), [item])
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

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
                selector=bot.SAVE_SELECTOR,
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
            save_button = MagicMock()
            page.locator.return_value.first = save_button
            playwright = MagicMock()
            browser = playwright.chromium.launch.return_value
            context = browser.new_context.return_value
            context.new_page.return_value = page
            manager = MagicMock()
            manager.__enter__.return_value = playwright
            actions = []
            extracted_item = {
                "url": "https://books.byui.edu/current_book/lesson_one",
                "filename": "lesson_1.html",
                "source_title": "English title",
                "source_subtitle": "Letter of Appreciation",
                "translated_filepath": str(translated_file),
            }

            bot._ensure_login = Mock()
            bot._refresh_injection_urls = Mock(return_value=[extracted_item])
            bot._open_toc_item = Mock()
            bot._open_editor = Mock()
            bot._set_chapter_title = Mock()
            bot._set_chapter_subtitle = Mock()
            html_source = MagicMock()
            bot._open_html_source = Mock(return_value=html_source)
            bot._replace_full_html_source = Mock()
            bot._close_editor = Mock()
            bot._read_chapter_title = Mock(return_value="Título traduzido")
            bot._read_chapter_subtitle = Mock(
                return_value="Carta de Agradecimento"
            )
            bot._copy_full_html_source = Mock(return_value="<p>Texto traduzido</p>")
            bot._verify_saved_html = Mock()

            with patch("bots.edtech_bot.sync_playwright", return_value=manager):
                bot.run_injection(
                    extracted_files=[extracted_item],
                    step_callback=lambda payload: actions.append(payload) or True,
                )

            action_names = [action["action"] for action in actions]
            self.assertNotIn("Open EdTech for the login check", action_names)
            self.assertIn('Click "Save"', action_names)
            self.assertIn("Close the editor", action_names)
            self.assertIn("Reopen the editor for save verification", action_names)
            self.assertIn('Click "HTML" for save verification', action_names)
            self.assertIn("Close the verified editor", action_names)
            self.assertLess(
                action_names.index("Replace the translated chapter title"),
                action_names.index('Click "HTML"'),
            )
            self.assertLess(
                action_names.index('Click "HTML"'),
                action_names.index("Replace the complete HTML source"),
            )
            self.assertLess(
                action_names.index("Replace the complete HTML source"),
                action_names.index('Click "Save"'),
            )
            self.assertEqual(
                actions[action_names.index("Replace the complete HTML source")]["text_to_copy"],
                "<p>Texto traduzido</p>",
            )
            bot._ensure_login.assert_called_once_with(page)
            bot._refresh_injection_urls.assert_called_once_with(page, [extracted_item])
            bot._open_toc_item.assert_called_once_with(page, extracted_item)
            self.assertEqual(bot._open_editor.call_count, 2)
            bot._set_chapter_title.assert_called_once_with(page, "Título traduzido")
            bot._set_chapter_subtitle.assert_called_once_with(
                page,
                "Carta de Agradecimento",
            )
            self.assertEqual(bot._open_html_source.call_count, 2)
            bot._replace_full_html_source.assert_called_once_with(
                page,
                html_source,
                "<p>Texto traduzido</p>",
            )
            save_button.click.assert_called_once_with()
            self.assertEqual(bot._close_editor.call_count, 2)
            bot._verify_saved_html.assert_called_once_with(
                extracted_item,
                extracted_item["url"],
                "<p>Texto traduzido</p>",
                "<p>Texto traduzido</p>",
            )
            context.close.assert_called_once_with()
            browser.close.assert_called_once_with()
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_reads_title_from_the_editable_chapter_heading(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, workspace, True)
        bot = EdTechScraperBot(
            "https://books.byui.edu/current_book",
            "PTBR",
            str(workspace),
            print_callback=Mock(),
        )
        page = MagicMock()
        title_field = MagicMock()
        title_field.count.return_value = 1
        title_field.evaluate.return_value = "Academic Honesty, Ethics and Integrity"
        page.locator.return_value.first = title_field

        title = bot._read_chapter_title(page)

        self.assertEqual(title, "Academic Honesty, Ethics and Integrity")
        page.locator.assert_called_once_with(bot.TITLE_SELECTOR)
        script = title_field.evaluate.call_args.args[0]
        self.assertIn("element.innerText", script)

    def test_reads_subtitle_from_the_optional_editable_chapter_paragraph(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, workspace, True)
        bot = EdTechScraperBot(
            "https://books.byui.edu/current_book",
            "PTBR",
            str(workspace),
            print_callback=Mock(),
        )
        page = MagicMock()
        subtitle_field = MagicMock()
        subtitle_field.count.return_value = 1
        subtitle_field.evaluate.return_value = "Letter of Appreciation"
        page.locator.return_value.first = subtitle_field

        subtitle = bot._read_chapter_subtitle(page)

        self.assertEqual(subtitle, "Letter of Appreciation")
        page.locator.assert_called_once_with(bot.SUBTITLE_SELECTOR)
        script = subtitle_field.evaluate.call_args.args[0]
        self.assertIn("element.innerText", script)

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
            first_translated_page = workspace / "lesson_1_pt.html"
            second_translated_page = workspace / "lesson_2_pt.html"
            first_translated_page.write_text(
                '<div id="edtech-meta-title">Introdução</div><p>Primeiro</p>',
                encoding="utf-8",
            )
            second_translated_page.write_text(
                '<div id="edtech-meta-title">Planejando seu projeto</div><p>Segundo</p>',
                encoding="utf-8",
            )
            controller = Mock()
            controller._extract_page_title.side_effect = (
                lambda content, _ext: re.search(
                    r'<div id="edtech-meta-title">(.*?)</div>', content
                ).group(1)
            )
            controller.update_excel_dashboard.return_value = "report.xlsx"
            controller.get_gemini_translation_pages.return_value = [
                {"filepath": str(first_translated_page)},
                {"filepath": str(second_translated_page)},
            ]

            report_path = generate_edtech_excel_report(
                controller,
                "https://books.byui.edu/web_frontend_development_ii",
                "SPA",
                [
                    {
                        "filename": "lesson_1.html",
                        "raw_filepath": str(first_page),
                        "translated_filepath": str(first_translated_page),
                    },
                    {
                        "filename": "lesson_2.html",
                        "raw_filepath": str(second_page),
                        "translated_filepath": str(second_translated_page),
                    },
                ],
            )

            self.assertEqual(report_path, "report.xlsx")
            controller.update_excel_dashboard.assert_called_once_with(
                report_name="Web Frontend Development Ii EdTech Master",
                report_code="EDTECH-SPA",
                review_pages=[
                    {
                        "title": "Introdução",
                        "filepath": str(first_translated_page),
                        "status": "Translated",
                        "details": "",
                    },
                    {
                        "title": "Planejando seu projeto",
                        "filepath": str(second_translated_page),
                        "status": "Translated",
                        "details": "",
                    },
                ],
                excluded_sheets=("Dashboard", "Bot Analysis", "Raw Logs"),
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_translation_failure_reports_and_returns_successful_injection_subset(self):
        workspace = Path.cwd() / "tests" / f"_edtech_test_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True)
        try:
            successful_raw_page = workspace / "lesson_1.html"
            failed_raw_page = workspace / "lesson_2.html"
            successful_translated_page = workspace / "translated" / "lesson_1.html"
            failed_translated_page = workspace / "translated" / "lesson_2.html"
            successful_raw_page.write_text(
                '<div id="edtech-meta-title">First Source Lesson</div>',
                encoding="utf-8",
            )
            failed_raw_page.write_text(
                '<div id="edtech-meta-title">Source Lesson</div>',
                encoding="utf-8",
            )
            successful_translated_page.parent.mkdir()
            successful_translated_page.write_text(
                '<div id="edtech-meta-title">Primeira lição</div>',
                encoding="utf-8",
            )
            failed_translated_page.write_text(
                failed_raw_page.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            controller = Mock()
            controller.translate_files.side_effect = RuntimeError("batch failed")
            controller.get_gemini_translation_pages.return_value = [{
                "filepath": str(successful_translated_page),
            }]
            controller._extract_page_title.side_effect = [
                "Primeira lição",
                "Source Lesson",
            ]
            controller.update_excel_dashboard.return_value = "failed-report.xlsx"
            successful_item = {
                "filename": "lesson_1.html",
                "raw_filepath": str(successful_raw_page),
                "translated_filepath": str(successful_translated_page),
            }
            failed_item = {
                "filename": "lesson_2.html",
                "raw_filepath": str(failed_raw_page),
                "translated_filepath": str(failed_translated_page),
            }
            extracted = [successful_item, failed_item]

            outcome = translate_edtech_files_and_generate_report(
                controller,
                "https://books.byui.edu/demo",
                "PTBR",
                extracted,
            )

            self.assertEqual(outcome["report_path"], "failed-report.xlsx")
            self.assertEqual(outcome["translated_pages"], [successful_item])
            self.assertEqual(outcome["failed_pages"], [failed_item])
            self.assertEqual(str(outcome["translation_error"]), "batch failed")

            controller.update_excel_dashboard.assert_called_once_with(
                report_name="Demo EdTech Master",
                report_code="EDTECH-PTBR",
                review_pages=[
                    {
                        "title": "Primeira lição",
                        "filepath": str(successful_translated_page),
                        "status": "Translated",
                        "details": "",
                    },
                    {
                        "title": "Source Lesson",
                        "filepath": str(failed_raw_page),
                        "status": "Failed",
                        "details": "batch failed",
                    },
                ],
                excluded_sheets=("Dashboard", "Bot Analysis", "Raw Logs"),
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
