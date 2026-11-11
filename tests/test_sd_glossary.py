import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.sd_glossary import SoftwareDevelopmentGlossary


class SoftwareDevelopmentGlossaryTests(unittest.TestCase):
    def test_github_stack_applies_course_then_sd_then_general_priority(self):
        root = Path.cwd() / "tests" / f"_sd_glossary_{uuid.uuid4().hex}"
        try:
            glossary_dir = root / "Glossary" / "sd_glossaries"
            glossary_dir.mkdir(parents=True)
            (root / "Glossary" / "glossary.json").write_text(
                '{"Assignment": {"PTBR": "Geral"}, '
                '"Project": {"PTBR": "Projeto geral"}, '
                '"General only": {"PTBR": "Somente geral"}}',
                encoding="utf-8",
            )
            (glossary_dir / "global-sd-glossary.md").write_text(
                "| English | Portuguese (Brazil) | Context |\n"
                "| --- | --- | --- |\n"
                "| Assignment | Tarefa SD | SD context |\n"
                "| Project | Projeto SD | SD context |\n"
                "| SD only | Somente SD | SD context |\n",
                encoding="utf-8",
            )
            course_path = root / "course-glossary.md"
            course_path.write_text(
                "| English Term | PT-BR Translation | Context |\n"
                "| --- | --- | --- |\n"
                "| Assignment | Trabalho do Curso | First context |\n"
                "| Assignment | Tarefa do Curso | Second context |\n"
                "| English Term | PT-BR Translation | Context |\n"
                "| --- | --- | --- |\n"
                "| Course only | Somente curso | Course context |\n",
                encoding="utf-8",
            )

            glossary = SoftwareDevelopmentGlossary.load_github_stack(
                root, course_path, "PTBR"
            )
            mapping = glossary.relevant_mapping(
                "Assignment Project General only SD only Course only"
            )

            self.assertEqual(
                mapping["Assignment"],
                [
                    "Trabalho do Curso (context: First context)",
                    "Tarefa do Curso (context: Second context)",
                ],
            )
            self.assertEqual(mapping["Project"], "Projeto SD (context: SD context)")
            self.assertEqual(mapping["General only"], "Somente geral")
            self.assertEqual(mapping["SD only"], "Somente SD (context: SD context)")
            self.assertEqual(mapping["Course only"], "Somente curso (context: Course context)")
            self.assertFalse(
                any(row["english"] == "English Term" for row in glossary.rows)
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_github_stack_allows_course_glossary_to_be_skipped(self):
        root = Path.cwd() / "tests" / f"_sd_glossary_skip_{uuid.uuid4().hex}"
        try:
            glossary_dir = root / "Glossary" / "sd_glossaries"
            glossary_dir.mkdir(parents=True)
            (root / "Glossary" / "glossary.json").write_text(
                '{"Assignment": {"PTBR": "Geral"}, '
                '"General only": {"PTBR": "Somente geral"}}',
                encoding="utf-8",
            )
            (glossary_dir / "global-sd-glossary.md").write_text(
                "| English | Portuguese (Brazil) | Context |\n"
                "| --- | --- | --- |\n"
                "| Assignment | Tarefa SD | SD context |\n",
                encoding="utf-8",
            )

            glossary = SoftwareDevelopmentGlossary.load_github_stack(
                root, None, "PTBR"
            )
            mapping = glossary.relevant_mapping("Assignment General only")

            self.assertEqual(mapping["Assignment"], "Tarefa SD (context: SD context)")
            self.assertEqual(mapping["General only"], "Somente geral")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_learning_activities_uses_approved_portuguese_plural(self):
        hub_dir = Path(__file__).resolve().parents[1]
        glossary_path = SoftwareDevelopmentGlossary.default_path(hub_dir)
        glossary = SoftwareDevelopmentGlossary.load(glossary_path, "PTBR")

        mapping = glossary.relevant_mapping(
            "Complete all Learning Activities before continuing."
        )

        self.assertEqual(
            mapping["learning activities"],
            "atividades de aprendizagem (context: experiences designed to help learners acquire specific knowledge, skills, or attitudes)",
        )
        self.assertNotIn("aprendizado", mapping["learning activities"].casefold())

    def test_course_naming_terms_are_available_to_github_translation(self):
        hub_dir = Path(__file__).resolve().parents[1]
        glossary_path = SoftwareDevelopmentGlossary.default_path(hub_dir)
        glossary = SoftwareDevelopmentGlossary.load(glossary_path, "PTBR")

        mapping = glossary.relevant_mapping(
            "Activity Instructions Assignment Audit and Submission Check Your Understanding "
            "Course Content Exam Exam Instructions Final Exam Getting Help Instructions "
            "Optional Resources Overview Page Audit Prepare Project Project Requirements "
            "Setup Submission Task"
        )

        expected = {
            "Activity Instructions": "Instruções da Atividade",
            "Assignment": "Tarefa",
            "Audit and Submission": "Auditoria e Envio",
            "Check Your Understanding": "Avalie Seu Conhecimento",
            "Course Content": "Conteúdo do Curso",
            "Exam": "Prova",
            "Exam Instructions": "Instruções para a Prova",
            "Final Exam": "Prova Final",
            "Getting Help": "Obtendo Ajuda",
            "Instructions": "Instruções",
            "Optional Resources": "Recursos Opcionais",
            "Overview": "Visão Geral",
            "Page Audit": "Auditoria de Páginas",
            "Prepare": "Preparação",
            "Project": "Projeto",
            "Project Requirements": "Requisitos do Projeto",
            "Setup": "Configuração",
            "Submission": "Envio",
            "Task": "Tarefa",
        }
        for english, portuguese in expected.items():
            self.assertIn(english, mapping)
            self.assertTrue(mapping[english].startswith(portuguese))


if __name__ == "__main__":
    unittest.main()
