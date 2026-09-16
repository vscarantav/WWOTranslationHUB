import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.edtech_bot import EdTechScraperBot
from main_ui import validate_edtech_shell_details


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


if __name__ == "__main__":
    unittest.main()
