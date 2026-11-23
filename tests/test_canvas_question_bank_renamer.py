import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.canvas_question_bank_renamer import (  # noqa: E402
    CanvasQuestionBankError,
    CanvasQuestionBankRenamer,
    format_question_bank_name,
)
from core.translation_id_registry import (  # noqa: E402
    LANGUAGES,
    TranslationIdRegistry,
    empty_language_instance,
)


def bank_item(translation_id, title, stable_key):
    instances = {language: empty_language_instance(language) for language in LANGUAGES}
    instances["EN"]["title"] = title
    return {
        "translation_id": translation_id,
        "short_id": translation_id.split("-", 1)[1],
        "item_type": "Question Bank",
        "source_title": title,
        "stable_key": stable_key,
        "package_paths": [f"non_cc_assessments/{stable_key}.xml.qti"],
        "placement": "question_bank_title",
        "retired": False,
        "instances": instances,
    }


class CanvasQuestionBankRenamerTests(unittest.TestCase):
    def setUp(self):
        self.registry = TranslationIdRegistry(
            "GS170",
            "123",
            [
                bank_item("GS170-QB-001", "QB: GS 170 W01 Questions", "bank-1"),
                bank_item("GS170-QB-002", "Unfiled Questions", "bank-2"),
            ],
        )
        self.service = CanvasQuestionBankRenamer(
            self.registry,
            "https://canvas.test/courses/123",
            "EN",
            "source-register",
            profile_dir=Path.home() / "WWOTranslationHUB-test-profile",
        )

    def test_plan_proposes_exact_names_and_reports_noneditable_unfiled(self):
        plan = self.service.plan([
            {
                "id": 10,
                "name": "QB: GS 170 W01 Questions",
                "url": "https://canvas.test/courses/123/question_banks/10",
                "editable": True,
            },
            {
                "id": 11,
                "name": "Unfiled Questions",
                "url": "https://canvas.test/courses/123/question_banks/11",
                "editable": False,
            },
        ])
        by_id = {change["translation_id"]: change for change in plan["changes"]}
        self.assertEqual(by_id["GS170-QB-001"]["status"], "Rename")
        self.assertEqual(
            by_id["GS170-QB-001"]["new_name"],
            "QB: GS 170 W01 Questions TranslationID: GS170-QB-001",
        )
        self.assertEqual(by_id["GS170-QB-002"]["status"], "Non-editable")
        self.assertIn("Unfiled Questions", by_id["GS170-QB-002"]["detail"])

    def test_plan_is_idempotent_and_detects_different_marker(self):
        correct = self.service.plan([
            {
                "id": 10,
                "name": "QB: GS 170 W01 Questions TranslationID: GS170-QB-001",
                "editable": True,
            },
            {"id": 11, "name": "Unfiled Questions", "editable": False},
        ])
        self.assertEqual(correct["changes"][0]["status"], "Correct")
        self.assertEqual(
            self.registry.items[0]["instances"]["EN"]["id_status"],
            "correct",
        )
        self.assertEqual(
            self.registry.items[0]["instances"]["EN"]["content_id"],
            "10",
        )

        conflict = self.service.plan([
            {
                "id": 10,
                "name": "QB: GS 170 W01 Questions TranslationID: GS170-QB-999",
                "editable": True,
            },
            {"id": 11, "name": "Unfiled Questions", "editable": False},
        ])
        self.assertEqual(conflict["changes"][0]["status"], "Conflict")

    def test_plan_reports_missing_duplicate_and_extra_banks(self):
        plan = self.service.plan([
            {"id": 10, "name": "QB: GS 170 W01 Questions", "editable": True},
            {"id": 12, "name": "QB: GS 170 W01 Questions", "editable": True},
            {"id": 99, "name": "Unexpected Bank", "editable": True},
        ])
        by_id = {change["translation_id"]: change for change in plan["changes"]}
        self.assertEqual(by_id["GS170-QB-001"]["status"], "Duplicate")
        self.assertEqual(by_id["GS170-QB-002"]["status"], "Missing")
        self.assertEqual(len(plan["extra_banks"]), 3)
        with self.assertRaisesRegex(CanvasQuestionBankError, "extra-bank"):
            self.service.validate_plan_for_apply(plan)

    def test_helper_is_idempotent_and_fails_closed(self):
        expected = "QB: GS 170 W01 Questions TranslationID: GS170-QB-001"
        self.assertEqual(
            format_question_bank_name("QB: GS 170 W01 Questions", "GS170-QB-001"),
            expected,
        )
        self.assertEqual(format_question_bank_name(expected, "GS170-QB-001"), expected)
        with self.assertRaises(CanvasQuestionBankError):
            format_question_bank_name(
                "QB: GS 170 W01 Questions TranslationID: GS170-QB-002",
                "GS170-QB-001",
            )

    def test_source_course_and_profile_safety_are_enforced(self):
        with self.assertRaisesRegex(CanvasQuestionBankError, "source course"):
            CanvasQuestionBankRenamer(
                self.registry,
                "https://canvas.test/courses/999",
                "EN",
                "source-register",
                profile_dir=Path.home() / "profile",
            )
        unsafe = CanvasQuestionBankRenamer(
            self.registry,
            "https://canvas.test/courses/123",
            "EN",
            "source-register",
            profile_dir=Path(__file__).resolve().parents[1] / "profile",
        )
        with self.assertRaisesRegex(CanvasQuestionBankError, "outside the repository"):
            unsafe._ensure_profile_is_outside_repository()


if __name__ == "__main__":
    unittest.main()

