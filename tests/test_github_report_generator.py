import shutil
import sys
import unittest
import uuid
from pathlib import Path

from openpyxl import load_workbook


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_report_generator import GitHubTranslationReportGenerator


class GitHubReportGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_github_report_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_workbook_has_exact_tabs_defaults_and_dropdowns(self):
        path = GitHubTranslationReportGenerator(self.root).generate(
            "course-test1-pt",
            [{"page_name": "Lesson", "type": "Markdown", "status": "Translated"}],
            [
                {"page_title": "One", "context_summary": "input", "variable_en": "name", "variable_pt": "nome", "source_file": "one.md"},
                {"page_title": "Two", "context_summary": "input", "variable_en": "name", "variable_pt": "nome", "source_file": "two.md"},
            ],
            [{
                "asset_path": "images/a.png",
                "package": "External",
                "target_language_link": "https://personal-user.github.io/course-test1-pt/week01/lesson.html",
                "resource_link": "https://personal-user.github.io/course-test1-pt/images/a.png",
                "alt_text_en": "A",
                "alt_text_pt": "Um",
            }],
        )
        workbook = load_workbook(path)
        self.assertEqual(workbook.sheetnames, ["Reviewing", "Variables", "Resources"])
        resources = workbook["Resources"]
        self.assertEqual(resources["A1"].value, "Resources")
        self.assertEqual([resources.cell(3, column).value for column in range(1, 12)], [
            "Num", "Status", "Images (Copy from UniqueImages)", "Package",
            "Has Text", "Plan", "Target Language Link", "Resource Link", "Notes",
            "Alt Text EN", "Alt Text PT",
        ])
        self.assertEqual(resources["A4"].value, 1)
        self.assertEqual(resources["B4"].value, "To Do")
        self.assertEqual(resources["C4"].value, "images/a.png")
        self.assertEqual(resources["D4"].value, "External")
        self.assertIsNone(resources["E4"].value)
        self.assertIsNone(resources["F4"].value)
        self.assertEqual(
            resources["G4"].hyperlink.target,
            "https://personal-user.github.io/course-test1-pt/week01/lesson.html",
        )
        self.assertEqual(
            resources["H4"].hyperlink.target,
            "https://personal-user.github.io/course-test1-pt/images/a.png",
        )
        formulas = [
            validation.formula1
            for validation in resources.data_validations.dataValidation
        ]
        self.assertTrue(any("To Do" in formula and "Done" in formula for formula in formulas))
        self.assertTrue(any(
            all(option in formula for option in (
                "Canvas", "External", "GitHub", "API Setting",
                "Video", "Image", "Codepen",
            ))
            and "LLDOC" not in formula
            for formula in formulas
        ))
        self.assertTrue(any(
            "Find Equivalent" in formula and "Fix Link" in formula and "Use Current" in formula
            for formula in formulas
        ))
        self.assertTrue(resources.conditional_formatting)
        self.assertTrue(workbook["Variables"].conditional_formatting)
