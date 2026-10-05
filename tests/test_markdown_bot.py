import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.markdown_bot import MarkdownTranslationBot


class _Response:
    def __init__(self, text):
        self.text = text


class _TranslationModel:
    def generate_content(self, prompt, request_options=None):
        content = prompt.split("\n\nCONTENT:\n", 1)[1]
        return _Response(content.replace("Student name", "Nome do aluno"))


class MarkdownTranslationBotTests(unittest.TestCase):
    def test_translates_prose_but_preserves_code_urls_and_frontmatter(self):
        source = (
            "---\ntitle: Student name\n---\n\n# Student name\n"
            "Use `student_name` at [the site](https://example.com/path).\n\n"
            "```python\nstudent_name = input()\n```\n"
        )
        translated = MarkdownTranslationBot(model=_TranslationModel()).translate(source)
        self.assertIn("# Nome do aluno", translated)
        self.assertIn("title: Student name", translated)
        self.assertIn("`student_name`", translated)
        self.assertIn("https://example.com/path", translated)
        self.assertIn("student_name = input()", translated)

