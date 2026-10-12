import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.sd_glossary import SoftwareDevelopmentGlossary


class SoftwareDevelopmentGlossaryTests(unittest.TestCase):
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
