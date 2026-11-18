import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from main_ui import CourseTranslationHubUI


class _ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


class _FakeController:
    MAX_STANDALONE_OFFICE_DOCUMENTS = 20
    SUPPORTED_STANDALONE_OFFICE_EXTENSIONS = {".docx", ".xlsx"}
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.__class__.instances.append(self)

    def translate_office_documents(self, paths, progress_callback=None):
        self.calls.append((tuple(paths), progress_callback))
        return {
            "success_count": len(paths),
            "skipped_count": 0,
            "failure_count": 0,
            "output_directories": ["Translated PTBR"],
            "report_path": "report.xlsx",
            "report_error": "",
        }


class OfficeDocumentUITests(unittest.TestCase):
    def _make_ui(self):
        ui = CourseTranslationHubUI.__new__(CourseTranslationHubUI)
        ui.root = Mock()
        ui.root.after.side_effect = (
            lambda _delay, callback, *args: callback(*args)
        )
        ui.office_lang_var = Mock()
        ui.office_lang_var.get.return_value = "PTBR"
        ui.disable_buttons = Mock()
        ui.enable_buttons = Mock()
        ui._update_office_document_progress = Mock()
        ui._show_office_document_summary = Mock()
        return ui

    def test_legacy_doc_or_xls_selection_shows_conversion_message(self):
        ui = self._make_ui()

        with patch(
            "main_ui.filedialog.askopenfilenames",
            return_value=("legacy.doc", "legacy.xls"),
        ), patch("main_ui.messagebox.showerror") as showerror:
            ui.run_office_document_translation()

        ui.disable_buttons.assert_not_called()
        showerror.assert_called_once()
        title, message = showerror.call_args.args
        self.assertIn("Older Office Formats", title)
        self.assertIn(".doc", message)
        self.assertIn(".xls", message)
        self.assertIn(".docx", message)
        self.assertIn(".xlsx", message)

    def test_valid_mixed_selection_calls_standalone_controller_flow(self):
        ui = self._make_ui()
        _FakeController.instances = []
        selected = ("lesson.docx", "scores.xlsx")

        with patch(
            "main_ui.filedialog.askopenfilenames",
            return_value=selected,
        ), patch("main_ui.TranslationController", _FakeController), patch(
            "main_ui.threading.Thread",
            _ImmediateThread,
        ):
            ui.run_office_document_translation()

        self.assertEqual(len(_FakeController.instances), 1)
        controller = _FakeController.instances[0]
        self.assertEqual(
            controller.kwargs,
            {"target_language": "PTBR", "initialize_workspace": False},
        )
        self.assertEqual(controller.calls[0][0], selected)
        ui.disable_buttons.assert_called_once_with()
        ui.enable_buttons.assert_called_once_with()
        ui._show_office_document_summary.assert_called_once()


if __name__ == "__main__":
    unittest.main()
