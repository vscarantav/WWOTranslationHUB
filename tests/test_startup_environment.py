import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from dotenv import dotenv_values


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from main_ui import CourseTranslationHubUI, ensure_required_environment


class StartupEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path.cwd() / "tests" / f"_startup_env_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ui_exits_before_initialization_when_configuration_is_refused(self):
        root = Mock()

        with patch("main_ui.ensure_required_environment", return_value=False):
            with self.assertRaises(SystemExit):
                CourseTranslationHubUI(root)

        root.destroy.assert_called_once_with()
        root.columnconfigure.assert_not_called()

    def test_prompts_for_and_saves_every_required_variable(self):
        env_file = self.temp_dir / ".env"
        env_file.write_text(
            "GEMINI_API_KEY=\nCANVAS_API_URL=\nCANVAS_API_TOKEN=\n",
            encoding="utf-8",
        )
        parent = Mock()

        with patch.dict(os.environ, {}, clear=True), patch(
            "main_ui.simpledialog.askstring",
            side_effect=[
                "gemini-value",
                "https://canvas.example.edu",
                "canvas-value",
            ],
        ) as askstring, patch("main_ui.messagebox.showerror") as showerror:
            self.assertTrue(ensure_required_environment(parent, str(env_file)))

            self.assertEqual(os.environ["GEMINI_API_KEY"], "gemini-value")
            self.assertEqual(
                os.environ["CANVAS_API_URL"],
                "https://canvas.example.edu",
            )
            self.assertEqual(os.environ["CANVAS_API_TOKEN"], "canvas-value")

        saved_values = dotenv_values(env_file)
        self.assertEqual(saved_values["GEMINI_API_KEY"], "gemini-value")
        self.assertEqual(
            saved_values["CANVAS_API_URL"],
            "https://canvas.example.edu",
        )
        self.assertEqual(saved_values["CANVAS_API_TOKEN"], "canvas-value")
        self.assertEqual(askstring.call_count, 3)
        self.assertEqual(askstring.call_args_list[0].kwargs["show"], "*")
        self.assertNotIn("show", askstring.call_args_list[1].kwargs)
        self.assertEqual(askstring.call_args_list[2].kwargs["show"], "*")
        showerror.assert_not_called()

    def test_cancellation_blocks_startup_without_saving_partial_values(self):
        env_file = self.temp_dir / ".env"
        original_content = (
            "GEMINI_API_KEY=\nCANVAS_API_URL=\nCANVAS_API_TOKEN=\n"
        )
        env_file.write_text(original_content, encoding="utf-8")
        parent = Mock()

        with patch.dict(os.environ, {}, clear=True), patch(
            "main_ui.simpledialog.askstring",
            side_effect=["gemini-value", None],
        ), patch("main_ui.messagebox.showerror") as showerror:
            self.assertFalse(ensure_required_environment(parent, str(env_file)))

            self.assertNotIn("GEMINI_API_KEY", os.environ)
            self.assertEqual(env_file.read_text(encoding="utf-8"), original_content)

        showerror.assert_called_once_with(
            "Required Configuration Missing",
            "CANVAS_API_URL is required. Translation Hub cannot start without it.",
            parent=parent,
        )

    def test_prompts_for_additional_variables_declared_in_env(self):
        env_file = self.temp_dir / ".env"
        env_file.write_text("EXTRA_SERVICE_SECRET=\n", encoding="utf-8")
        parent = Mock()

        with patch.dict(os.environ, {}, clear=True), patch(
            "main_ui.simpledialog.askstring",
            side_effect=["gemini", "https://canvas.example.edu", "canvas", "extra"],
        ) as askstring, patch("main_ui.messagebox.showerror"):
            self.assertTrue(ensure_required_environment(parent, str(env_file)))

        self.assertEqual(askstring.call_count, 4)
        self.assertEqual(
            dotenv_values(env_file)["EXTRA_SERVICE_SECRET"],
            "extra",
        )


if __name__ == "__main__":
    unittest.main()
