import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.qa_audit_bot import QAAuditBot
from course_auditor import CourseAuditor


class _Response:
    def __init__(self, text):
        self.text = text


class _Model:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def generate_content(self, prompt, request_options=None):
        self.prompts.append(prompt)
        return _Response(self.text)


class QAAuditLanguageTests(unittest.TestCase):
    def test_spanish_audit_uses_spanish_prompt_and_output_column(self):
        model = _Model(
            "| Location / Element | English (Canon) | Spanish (Translated) | Discrepancy Type | Description |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Paragraph 1 | Hello | Hola | Different Content | Example |"
        )
        bot = QAAuditBot(target_language="SPA", model=model)

        rows = bot.audit_content("Hello", "Hola")

        self.assertIn("Spanish translation", bot.system_prompt)
        self.assertIn("Spanish (Translated)", model.prompts[0])
        self.assertEqual(rows[0]["Spanish (Translated)"], "Hola")

    def test_language_is_inferred_from_translated_package_name(self):
        self.assertEqual(
            CourseAuditor._infer_target_language("my_course_SPA.imscc"),
            "SPA",
        )
        self.assertEqual(
            CourseAuditor._infer_target_language("my_course_es.imscc"),
            "SPA",
        )
        self.assertEqual(
            CourseAuditor._infer_target_language("my_course_PTBR.imscc"),
            "PTBR",
        )


if __name__ == "__main__":
    unittest.main()
