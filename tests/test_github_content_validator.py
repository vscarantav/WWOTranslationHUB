import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_content_validator import GitHubContentValidator


class GitHubContentValidatorWeekLabelTests(unittest.TestCase):
    def test_rejects_visible_english_week_labels(self):
        validator = GitHubContentValidator()
        original = '<a href="../week01/index.html">W1</a><p>Week 02 overview.</p>'
        translated = '<a href="../week01/index.html">W1</a><p>Visão geral.</p>'

        errors = validator.validate(original, translated, ".html")

        self.assertTrue(any("English week label" in error for error in errors))

    def test_allows_portuguese_labels_and_ignores_urls_and_code(self):
        validator = GitHubContentValidator()
        original = (
            '<a href="../week01/index.html">W1</a>'
            '<script>const label = "W02";</script>'
        )
        translated = (
            '<a href="../week01/index.html">S1</a>'
            '<script>const label = "W02";</script>'
        )

        errors = validator.validate(original, translated, ".html")

        self.assertFalse(any("English week label" in error for error in errors))

    def test_rejects_deprecated_learning_activity_translation(self):
        validator = GitHubContentValidator()

        errors = validator.validate(
            "Complete all learning activities.",
            "Conclua todas as atividades de aprendizado.",
            ".html",
        )

        self.assertTrue(any("Glossary violation" in error for error in errors))

    def test_accepts_approved_learning_activity_translation(self):
        validator = GitHubContentValidator()

        errors = validator.validate(
            "Complete all learning activities.",
            "Conclua todas as atividades de aprendizagem.",
            ".html",
        )

        self.assertFalse(any("Glossary violation" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
