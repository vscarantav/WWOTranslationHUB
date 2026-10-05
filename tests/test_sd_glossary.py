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


if __name__ == "__main__":
    unittest.main()
