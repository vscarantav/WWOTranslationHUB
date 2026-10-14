import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.html_bot import HTMLTranslationBot
from bots.txt_bot import TextTranslationBot
from bots.xml_bot import XMLTranslationBot


class TranslationBotsFailClosedTests(unittest.TestCase):
    @staticmethod
    def _unconfigured(bot_class):
        bot = bot_class.__new__(bot_class)
        bot.client_ready = False
        bot._log = Mock()
        return bot

    def test_html_bot_raises_instead_of_returning_source(self):
        bot = self._unconfigured(HTMLTranslationBot)
        with self.assertRaises(RuntimeError):
            bot.translate_html_content("<p>Hello</p>")

    def test_text_bot_raises_instead_of_returning_source(self):
        bot = self._unconfigured(TextTranslationBot)
        with self.assertRaises(RuntimeError):
            bot.translate_txt_content("Hello")

    def test_xml_bot_raises_instead_of_returning_source(self):
        bot = self._unconfigured(XMLTranslationBot)
        with self.assertRaises(RuntimeError):
            bot.translate_xml_content("<title>Hello</title>")

    def test_standard_html_bot_rejects_unchanged_english(self):
        bot = HTMLTranslationBot(api_key="test-key")
        bot._log = Mock()
        bot.model.generate_content = lambda prompt, request_options=None: Mock(
            text=prompt.rsplit("Content to translate:\n", 1)[1]
        )
        with self.assertRaisesRegex(RuntimeError, "unchanged in English"):
            bot.translate_html_content(
                "<p>This is the lesson for you and your class.</p>"
            )

    def test_text_bot_rejects_unchanged_english(self):
        bot = TextTranslationBot(api_key="test-key")
        bot._log = Mock()
        bot.model.generate_content = lambda prompt, request_options=None: Mock(
            text=prompt.rsplit("Content to translate:\n", 1)[1]
        )
        with self.assertRaisesRegex(RuntimeError, "unchanged in English"):
            bot.translate_txt_content("This is the lesson for you and your class.")

    def test_xml_bot_rejects_unchanged_english_nodes(self):
        bot = XMLTranslationBot(api_key="test-key")
        bot._log = Mock()
        bot.model.generate_content = lambda prompt, request_options=None: Mock(
            text=prompt.rsplit("Content:\n", 1)[1]
        )
        with patch("bots.xml_bot.time.sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Unable to translate XML batch"):
                bot.translate_xml_content(
                    "<lesson><description>This is the lesson for you and your class.</description></lesson>"
                )


if __name__ == "__main__":
    unittest.main()
