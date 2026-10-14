import json
import sys
import unittest
from unittest.mock import Mock
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from controller import TranslationController
from reprocess_failed import _failed_files_from_log, _infer_translation_context


class ArchitectureRuntimeTests(unittest.TestCase):
    def test_architecture_has_no_case_insensitive_duplicate_keys(self):
        def reject_duplicate_keys(pairs):
            result = {}
            normalized = set()
            for key, value in pairs:
                folded = key.casefold()
                if folded in normalized:
                    raise ValueError(f"Duplicate JSON key: {key}")
                normalized.add(folded)
                result[key] = value
            return result

        json.loads(
            (APP_DIR / "App_Architecture.json").read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )

    def test_controller_loads_renamed_architecture_file(self):
        controller = TranslationController.__new__(TranslationController)
        controller.app_dir = str(APP_DIR)

        instructions = controller._load_instructions()

        self.assertEqual(
            instructions["project_overview"]["name"],
            "Course Translation Hub",
        )
        self.assertIn("agent_prompts", instructions["bot_instructions"])

    def test_controller_fails_when_architecture_file_is_missing(self):
        controller = TranslationController.__new__(TranslationController)
        controller.app_dir = str(APP_DIR / "does-not-exist")
        with self.assertRaises(FileNotFoundError):
            controller._load_instructions()

    def test_controller_requires_every_language_prompt(self):
        controller = TranslationController.__new__(TranslationController)
        controller.target_language = "PTBR"
        controller.instructions = {"bot_instructions": {"agent_prompts": {}}}
        controller.bots = {
            extension: Mock()
            for extension in ("html", "xml", "qti", "txt")
        }
        with self.assertRaisesRegex(RuntimeError, "Required translation prompts"):
            controller._apply_custom_prompts()

    def test_recovery_understands_windows_output_path_and_language(self):
        name, language = _infer_translation_context(
            r"C:\hub\Courses to Translate\course_one_SPA\quiz\assessment_qti.xml"
        )
        self.assertEqual(name, "course_one")
        self.assertEqual(language, "SPA")

    def test_recovery_prioritizes_final_retry_failures(self):
        lines = [
            r"Translation failed for C:\hub\course_PTBR\first.xml: temporary\n",
            r"Retry failed for C:\hub\course_PTBR\final.xml: still invalid\n",
        ]
        self.assertEqual(
            _failed_files_from_log(lines),
            [r"C:\hub\course_PTBR\final.xml"],
        )

    def test_recovery_does_not_reprocess_a_successful_retry(self):
        filepath = r"C:\hub\course_PTBR\recovered.xml"
        lines = [
            f"Translation failed for {filepath}: temporary\n",
            f"Retry succeeded for {filepath}\n",
        ]
        self.assertEqual(_failed_files_from_log(lines), [])


if __name__ == "__main__":
    unittest.main()
