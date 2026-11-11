import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.cse_glossary_agent import CSEGlossaryAgent
from core.cse_glossary import CSEGlossaryLayer, CSEGlossaryStack
from main_ui import CourseTranslationHubUI


class CSEGlossaryLayerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_cse_glossary_{uuid.uuid4().hex}"
        glossary_dir = self.root / "Glossary" / "sd_glossaries"
        glossary_dir.mkdir(parents=True)
        (self.root / "Glossary" / "glossary.json").write_text(
            json.dumps(
                {
                    "Assignment": {"PTBR": "Tarefa geral", "SPA": "Tarea general"},
                    "General only": {"PTBR": "Somente geral"},
                }
            ),
            encoding="utf-8",
        )
        (glossary_dir / "global-sd-glossary.md").write_text(
            "| English | PT-BR Translation | Context |\n"
            "| --- | --- | --- |\n"
            "| Assignment | Tarefa SD | Software-development coursework |\n"
            "| Repository | Repositório | Git source repository |\n",
            encoding="utf-8",
        )
        self.course_path = self.root / "course.md"
        self.course_path.write_text(
            "# Course glossary\n\n"
            "| English Term | PT-BR Translation | Context |\n"
            "| --- | --- | --- |\n"
            "| Assignment | Trabalho WDD | WDD deliverable |\n"
            "| Course only | Somente WDD | WDD course concept |\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stack_keeps_three_independent_agents_in_priority_order(self):
        stack = CSEGlossaryStack.load(self.root, "PTBR", self.course_path)

        self.assertEqual(
            [layer.name for layer in stack.layers],
            [
                "General glossary",
                "Global software-development glossary",
                "Course-specific glossary",
            ],
        )
        self.assertEqual([layer.priority for layer in stack.layers], [1, 2, 3])
        self.assertEqual(
            stack.layers[0].relevant_entries("Complete the Assignment.")[0]["translation"],
            "Tarefa geral",
        )
        self.assertEqual(
            stack.layers[1].relevant_entries("Complete the Assignment.")[0]["translation"],
            "Tarefa SD",
        )
        self.assertEqual(
            stack.layers[2].relevant_entries("Complete the Assignment.")[0]["translation"],
            "Trabalho WDD",
        )

    def test_spanish_uses_native_values_and_labels_portuguese_markdown_as_reference(self):
        stack = CSEGlossaryStack.load(self.root, "SPA", self.course_path)

        general = stack.layers[0].relevant_entries("Assignment General only")
        global_entry = stack.layers[1].relevant_entries("Repository")[0]
        course_entry = stack.layers[2].relevant_entries("Course only")[0]

        self.assertEqual(general[0]["translation"], "Tarea general")
        self.assertEqual(general[1]["translation"], "")
        self.assertEqual(general[1]["reference_language"], "PTBR")
        self.assertEqual(global_entry["translation"], "")
        self.assertEqual(global_entry["reference_translation"], "Repositório")
        self.assertEqual(global_entry["reference_language"], "PTBR")
        self.assertEqual(course_entry["reference_language"], "PTBR")

    def test_markdown_prefers_target_language_column_when_available(self):
        multilingual = self.root / "multilingual.md"
        multilingual.write_text(
            "| English Term | PT-BR Translation | Spanish Translation | French Translation | Context |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Assignment | Tarefa | Tarea | Devoir | Course work |\n",
            encoding="utf-8",
        )

        layer = CSEGlossaryLayer.from_markdown(
            multilingual, "FRA", "Course-specific glossary", 3
        )

        entry = layer.relevant_entries("Assignment")[0]
        self.assertEqual(entry["translation"], "Devoir")
        self.assertEqual(entry["reference_translation"], "Tarefa")


class CSEGlossaryAgentTests(unittest.TestCase):
    def test_replacements_change_visible_text_but_not_attributes_or_code(self):
        source = (
            '<div title="Old assignment"><p>Old assignment</p>'
            "<code>Old assignment</code></div>"
        )

        updated, count = CSEGlossaryAgent.apply_replacements(
            source,
            [{"find": "Old assignment", "replace": "Required term"}],
            "html",
        )

        self.assertEqual(count, 1)
        self.assertIn('title="Old assignment"', updated)
        self.assertIn("<p>Required term</p>", updated)
        self.assertIn("<code>Old assignment</code>", updated)

    def test_response_parser_accepts_json_fence_and_rejects_markup(self):
        replacements = CSEGlossaryAgent._parse_replacements(
            '```json\n{"replacements":[{"find":"Tarefa","replace":"Atividade"}]}\n```'
        )
        self.assertEqual(
            replacements,
            [{"find": "Tarefa", "replace": "Atividade"}],
        )
        with self.assertRaisesRegex(ValueError, "text only"):
            CSEGlossaryAgent._parse_replacements(
                '{"replacements":[{"find":"<p>Tarefa</p>","replace":"Atividade"}]}'
            )


class CSEIMSCCPromptTests(unittest.TestCase):
    def _ui(self):
        ui = CourseTranslationHubUI.__new__(CourseTranslationHubUI)
        ui.root = Mock()
        ui.hub_dir = str(Path.cwd())
        ui.lang_var = Mock()
        ui.lang_var.get.return_value = "PTBR"
        return ui

    def test_non_cse_goes_directly_to_imscc_picker_after_one_prompt(self):
        ui = self._ui()
        with patch("main_ui.messagebox.askyesno", return_value=False) as askyesno, patch(
            "main_ui.filedialog.askopenfilename", return_value=""
        ) as askopenfilename:
            ui.run_translation()

        askyesno.assert_called_once()
        self.assertEqual(askyesno.call_args.args[0], "CSE Course")
        self.assertEqual(
            askopenfilename.call_args.kwargs["title"],
            "Select an IMSCC File to Translate",
        )

    def test_cse_course_glossary_is_selected_and_validated_before_imscc(self):
        ui = self._ui()
        selected_course_glossary = str(Path.cwd() / "course.md")
        with patch(
            "main_ui.messagebox.askyesno", side_effect=[True, True]
        ) as askyesno, patch(
            "main_ui.filedialog.askopenfilename",
            side_effect=[selected_course_glossary, ""],
        ) as askopenfilename, patch(
            "core.cse_glossary.CSEGlossaryStack.load"
        ) as load_stack:
            ui.run_translation()

        self.assertEqual(askyesno.call_count, 2)
        self.assertEqual(askopenfilename.call_count, 2)
        self.assertEqual(
            askopenfilename.call_args_list[0].kwargs["title"],
            "Select Course-Specific CSE Glossary",
        )
        self.assertEqual(
            askopenfilename.call_args_list[1].kwargs["title"],
            "Select an IMSCC File to Translate",
        )
        load_stack.assert_called_once_with(
            ui.hub_dir,
            "PTBR",
            selected_course_glossary,
        )


if __name__ == "__main__":
    unittest.main()
