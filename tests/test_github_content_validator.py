import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_content_validator import GitHubContentValidator
from core.github_naming_normalizer import GitHubNamingNormalizer


class GitHubContentValidatorLanguageTests(unittest.TestCase):
    def test_accepts_target_language_change_from_naming_normalizer(self):
        original = (
            '<html lang="en-us"><head><title>Welcome</title></head>'
            '<body><p>Hello students.</p></body></html>'
        )
        translated = (
            '<html lang="en-us"><head><title>Boas-vindas</title></head>'
            '<body><p>Ola, estudantes.</p></body></html>'
        )

        for target_language, expected_html_language in {
            "PTBR": "pt-BR",
            "SPA": "es",
            "FRA": "fr",
        }.items():
            with self.subTest(target_language=target_language):
                normalized = GitHubNamingNormalizer(target_language).normalize(
                    original,
                    translated,
                    ".html",
                    "welcome.html",
                )
                normalized_soup = BeautifulSoup(normalized, "html.parser")
                errors = GitHubContentValidator(target_language).validate(
                    original,
                    normalized,
                    ".html",
                )

                self.assertEqual(normalized_soup.html["lang"], expected_html_language)
                self.assertEqual(errors, [])

    def test_rejects_unapproved_root_language(self):
        validator = GitHubContentValidator("SPA")
        original = '<html lang="en"><body><p>Hello.</p></body></html>'
        translated = '<html lang="pt-BR"><body><p>Hola.</p></body></html>'

        errors = validator.validate(original, translated, ".html")

        self.assertTrue(any("root language must be localized to es" in error for error in errors))

    def test_still_rejects_language_changes_on_nested_elements(self):
        validator = GitHubContentValidator()
        original = (
            '<html lang="en"><body><p lang="en">Hello students.</p></body></html>'
        )
        translated = (
            '<html lang="pt-BR"><body><p lang="pt-BR">Ola, estudantes.</p></body></html>'
        )

        errors = validator.validate(original, translated, ".html")

        self.assertTrue(any("protected attributes" in error for error in errors))


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

    def test_accepts_only_approved_variable_changes_in_html_code(self):
        validator = GitHubContentValidator()
        original = '<p>Student name.</p><script>const student_name = input;</script>'
        translated = '<p>Nome do aluno.</p><script>const nome_aluno = input;</script>'

        errors = validator.validate(
            original,
            translated,
            ".html",
            variable_mapping={"student_name": "nome_aluno"},
        )

        self.assertFalse(any("approved Portuguese variable" in error for error in errors))

    def test_rejects_unapproved_code_change_during_variable_application(self):
        validator = GitHubContentValidator()
        original = '<p>Student name.</p><script>const student_name = input;</script>'
        translated = '<p>Nome do aluno.</p><script>let nome_aluno = input;</script>'

        errors = validator.validate(
            original,
            translated,
            ".html",
            variable_mapping={"student_name": "nome_aluno"},
        )

        self.assertTrue(any("approved Portuguese variable" in error for error in errors))

    def test_rejects_changed_markdown_structure(self):
        validator = GitHubContentValidator()
        errors = validator.validate(
            "# Heading\n\n- First\n- Second\n",
            "# TÃ­tulo\n\nPrimeiro\nSegundo\n",
            ".md",
        )
        self.assertTrue(any("Markdown delimiters" in error for error in errors))

    def test_rejects_malformed_xml(self):
        validator = GitHubContentValidator()
        errors = validator.validate(
            "<lesson><title>Hello</title></lesson>",
            "<lesson><title>OlÃ¡</lesson>",
            ".xml",
        )
        self.assertTrue(any("not well formed" in error for error in errors))

    def test_rejects_invalid_python_after_variable_application(self):
        validator = GitHubContentValidator()
        original = "```python\nstudent_name = input()\n```\n"
        translated = "```python\nnome_aluno = input(\n```\n"
        errors = validator.validate(
            original,
            translated,
            ".md",
            variable_mapping={"student_name": "nome_aluno"},
        )
        self.assertTrue(any("python is invalid" in error for error in errors))

    def test_allows_source_authored_incomplete_json_snippet(self):
        validator = GitHubContentValidator()
        original = (
            '<code class="json">"scripts": {"start": "node server.js"},</code>'
            '<p>Start the service.</p>'
        )
        translated = (
            '<code class="json">"scripts": {"start": "node server.js"},</code>'
            '<p>Inicie o servico.</p>'
        )

        errors = validator.validate(original, translated, ".html")

        self.assertFalse(any("json is invalid" in error for error in errors))

    def test_dedents_standalone_python_snippets(self):
        validator = GitHubContentValidator()
        original = (
            '<code class="python">\n  def main():\n    print("hello")\n</code>'
            '<p>Run the example.</p>'
        )
        translated = (
            '<code class="python">\n  def main():\n    print("hello")\n</code>'
            '<p>Execute o exemplo.</p>'
        )

        errors = validator.validate(original, translated, ".html")

        self.assertFalse(any("python is invalid" in error for error in errors))

    def test_rejects_new_syntax_error_when_source_snippet_is_valid(self):
        validator = GitHubContentValidator()
        original = '<code class="json">{"ready": true}</code><p>Ready.</p>'
        translated = '<code class="json">{"ready": }</code><p>Pronto.</p>'

        errors = validator.validate(original, translated, ".html")

        self.assertTrue(any("json is invalid" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
