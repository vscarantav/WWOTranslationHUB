import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.variable_extraction import (
    VariableApplicationError,
    VariableExtractor,
    VariableTranslator,
)


class VariableTranslatorTests(unittest.TestCase):
    def test_applies_variables_to_markdown_code_but_not_prose(self):
        source = (
            "Use student_name in this explanation.\n\n"
            "`student_name`\n\n"
            "```python\nstudent_name = input()\nprint(student_name)\n```\n"
        )

        translated, counts = VariableTranslator.apply(
            source, ".md", {"student_name": "nome_aluno"}
        )

        self.assertIn("Use student_name in this explanation.", translated)
        self.assertIn("`nome_aluno`", translated)
        self.assertIn("nome_aluno = input()", translated)
        self.assertIn("print(nome_aluno)", translated)
        self.assertEqual(counts["student_name"], 3)

    def test_applies_html_code_and_linked_dom_references_together(self):
        source = (
            '<p>The output variable is explained here.</p>'
            '<div id="output" aria-labelledby="output heading"></div>'
            '<script>const output = document.getElementById("output");\n'
            '// output is the destination\n'
            'output.textContent = "The output is ready";</script>'
            '<pre><code>let count = 1;\ncount += 1;</code></pre>'
        )

        translated, counts = VariableTranslator.apply(
            source,
            ".html",
            {"output": "saida", "count": "contagem"},
        )

        self.assertIn("The output variable is explained here.", translated)
        self.assertIn('id="saida"', translated)
        self.assertIn('aria-labelledby="saida heading"', translated)
        self.assertIn('const saida = document.getElementById("saida")', translated)
        self.assertIn("saida.textContent", translated)
        self.assertIn("// output is the destination", translated)
        self.assertIn('"The output is ready"', translated)
        self.assertIn("let contagem = 1", translated)
        self.assertIn("contagem += 1", translated)
        self.assertEqual(counts["output"], 5)
        self.assertEqual(counts["count"], 2)

    def test_identifier_boundaries_do_not_replace_substrings(self):
        source = "```js\nlet data = 1;\nlet database = data;\n```\n"

        translated, _ = VariableTranslator.apply(source, ".md", {"data": "dados"})

        self.assertIn("let dados = 1", translated)
        self.assertIn("let database = dados", translated)
        self.assertNotIn("dadosbase", translated)

    def test_rejects_invalid_or_colliding_translations(self):
        with self.assertRaises(VariableApplicationError):
            VariableTranslator.validate_mapping({"name": "função"})
        with self.assertRaises(VariableApplicationError):
            VariableTranslator.validate_mapping({"res": "resposta", "response": "resposta"})

    def test_rejects_naming_style_changes_and_reserved_words(self):
        with self.assertRaises(VariableApplicationError):
            VariableTranslator.validate_mapping({"studentName": "nome_aluno"})
        with self.assertRaises(VariableApplicationError):
            VariableTranslator.validate_mapping({"student_name": "class"})

    def test_protects_platform_and_external_environment_identifiers(self):
        source = (
            "<pre><code class='javascript'>"
            "const NODE_ENV = process.env.NODE_ENV || 'production';\n"
            "const PORT = process.env.PORT || 3000;\n"
            "const DATABASE_URL = process.env.DATABASE_URL;\n"
            "const __filename = fileURLToPath(import.meta.url);\n"
            "const __dirname = path.dirname(__filename);\n"
            "let message = 'Ready';\n"
            "console.log(message);"
            "</code></pre>"
        )

        protected = VariableTranslator.protected_identifiers(source, ".html")

        self.assertEqual(
            set(protected),
            {"NODE_ENV", "PORT", "DATABASE_URL", "__filename", "__dirname"},
        )
        self.assertNotIn("message", protected)

        mapping = VariableTranslator.enforce_protected_mapping(
            {
                "NODE_ENV": "AMBIENTE_NODE",
                "PORT": "PORTA",
                "DATABASE_URL": "URL_BANCO_DADOS",
                "__filename": "__nome_arquivo",
                "__dirname": "__nome_diretorio",
                "message": "mensagem",
            },
            protected,
        )
        translated, counts = VariableTranslator.apply(source, ".html", mapping)

        self.assertIn("const NODE_ENV = process.env.NODE_ENV", translated)
        self.assertIn("const PORT = process.env.PORT", translated)
        self.assertIn("const DATABASE_URL = process.env.DATABASE_URL", translated)
        self.assertIn("const __filename = fileURLToPath", translated)
        self.assertIn("const __dirname = path.dirname(__filename)", translated)
        self.assertIn("let mensagem = 'Ready'", translated)
        self.assertIn("console.log(mensagem)", translated)
        self.assertEqual(counts, {"message": 2})

    def test_extracts_lowercase_sql_table_and_column_identifiers(self):
        _fragments, candidates = VariableExtractor.extract(
            "```sql\ncreate table student_record (student_name TEXT, course_id INTEGER);\n```",
            ".md",
        )
        self.assertEqual(
            candidates,
            ["course_id", "student_name", "student_record"],
        )


if __name__ == "__main__":
    unittest.main()
