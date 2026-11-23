import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from controller import TranslationController  # noqa: E402
from core.canvas_question_bank_renamer import CanvasQuestionBankError  # noqa: E402
from core.canvas_translation_id_reconciler import APPROVAL_PHRASE  # noqa: E402


class TranslationIdControllerFlowTests(unittest.TestCase):
    def test_source_bank_blocker_is_checked_before_any_rest_write(self):
        controller = TranslationController.__new__(TranslationController)
        controller.enable_translation_ids = True
        controller.source_course_url = "https://canvas.test/courses/123"
        controller.hub_dir = str(APP_DIR.parent)
        controller.translation_id_registry_path = "registry.json"
        controller.translation_id_registry = Mock()
        controller.translation_id_registry.save = Mock()
        controller._translation_id_interaction = Mock(
            return_value=APPROVAL_PHRASE
        )
        controller._request_question_bank_approval = Mock(return_value=True)
        controller._require_translation_id_live_writes = Mock()

        bank_renamer = Mock()
        bank_renamer.validate_plan_for_apply.side_effect = CanvasQuestionBankError(
            "extra-bank result"
        )
        bank_plan = {"mode": "source-register", "language": "EN"}
        controller._plan_question_bank_registration = Mock(
            return_value=(bank_renamer, bank_plan)
        )

        rest_reconciler = Mock()
        rest_reconciler.plan.return_value = {
            "mode": "source-register",
            "language": "EN",
            "course_id": "123",
            "changes": [],
        }

        with patch(
            "controller.CanvasTranslationIdReconciler",
            return_value=rest_reconciler,
        ):
            with self.assertRaisesRegex(CanvasQuestionBankError, "extra-bank"):
                controller.register_source_canvas_ids()

        rest_reconciler.apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
