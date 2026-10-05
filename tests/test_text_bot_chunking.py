import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.txt_bot import TextTranslationBot


class _Response:
    def __init__(self, text):
        self.text = text


class _TextModel:
    def __init__(self):
        self.calls = []

    def generate_content(self, prompt, request_options=None):
        content = prompt.rsplit("Content to translate:\n", 1)[1]
        self.calls.append(content)
        return _Response(content.replace("Lesson", "Lição"))


class TextBotChunkingTests(unittest.TestCase):
    def test_large_text_is_translated_in_complete_bounded_chunks(self):
        model = _TextModel()
        bot = TextTranslationBot(api_key="test-key", target_language="PTBR")
        bot.model = model
        bot._log = lambda _message: None
        source = "".join(
            f"Lesson line {index:04d} contains complete instructional content.\n"
            for index in range(900)
        )

        translated = bot.translate_txt_content(source)

        self.assertGreater(len(model.calls), 3)
        self.assertTrue(all(len(chunk) <= 12000 for chunk in model.calls))
        self.assertEqual(translated.count("Lição line"), 900)
        self.assertIn("Lição line 0000", translated)
        self.assertIn("Lição line 0899", translated)

