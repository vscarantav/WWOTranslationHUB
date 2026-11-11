import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from bots.qa_audit_bot import QAAuditBot
from bots.scripturecheck_bot import ScriptureCheckBot
from bots.txt_bot import TextTranslationBot
from controller import TranslationController
from core.language_config import language_config
from core.link_processor import LinkProcessor
from course_auditor import CourseAuditor
from reprocess_failed import _infer_translation_context


class _Response:
    def __init__(self, text):
        self.text = text


class _Model:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def generate_content(self, prompt, request_options=None):
        self.prompts.append(prompt)
        return _Response(self.text)


class FrenchLanguageSupportTests(unittest.TestCase):
    def setUp(self):
        self.test_root = REPO_ROOT / "tests" / f"_french_support_{uuid.uuid4().hex}"
        self.test_root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_canonical_french_metadata(self):
        config = language_config("fra")

        self.assertEqual(config["name"], "French")
        self.assertEqual(config["church_code"], "fra")
        self.assertEqual(config["scripture_folder"], "fra")
        self.assertEqual(config["canvas_language"], "Français")

    def test_architecture_defines_every_french_agent_prompt(self):
        architecture = json.loads(
            (APP_DIR / "App_Architecture.json").read_text(encoding="utf-8")
        )
        prompts = architecture["bot_instructions"]["agent_prompts"]

        for agent in ("HTML", "XML", "QTI", "Text"):
            prompt = prompts[f"{agent}TranslationAgent_FRA"]
            self.assertIn("French", prompt)
            self.assertIn("translate", prompt.casefold())

    def test_controller_applies_all_french_agent_prompts(self):
        controller = TranslationController.__new__(TranslationController)
        controller.app_dir = str(APP_DIR)
        controller.target_language = "FRA"
        controller.instructions = controller._load_instructions()
        controller.bots = {
            extension: Mock()
            for extension in ("html", "xml", "qti", "txt")
        }

        controller._apply_custom_prompts()

        for bot in controller.bots.values():
            prompt = bot.set_system_prompt.call_args.args[0]
            self.assertIn("French", prompt)

    def test_ui_exposes_french_for_general_flows(self):
        ui_source = (APP_DIR / "main_ui.py").read_text(encoding="utf-8")

        self.assertGreaterEqual(ui_source.count('text="French (FRA)"'), 3)
        self.assertIn('text="French (FRA) — glossary pending"', ui_source)

    def test_french_qa_uses_french_prompt_and_column(self):
        model = _Model(
            "| Location / Element | English (Canon) | French (Translated) | Discrepancy Type | Description |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Paragraph 1 | Hello | Bonjour | Different Content | Example |"
        )
        bot = QAAuditBot(target_language="FRA", model=model)

        rows = bot.audit_content("Hello", "Bonjour")

        self.assertIn("French translation", bot.system_prompt)
        self.assertIn("French (Translated)", model.prompts[0])
        self.assertEqual(rows[0]["French (Translated)"], "Bonjour")

    def test_french_package_names_are_inferred_for_audit_and_recovery(self):
        self.assertEqual(
            CourseAuditor._infer_target_language("my_course_FRA.imscc"),
            "FRA",
        )
        self.assertEqual(
            CourseAuditor._infer_target_language("my_course_fr.imscc"),
            "FRA",
        )
        self.assertEqual(
            _infer_translation_context(r"C:\hub\course_one_FRA\quiz\assessment_qti.xml"),
            ("course_one", "FRA"),
        )

    def test_french_text_bot_names_language_in_default_prompt(self):
        bot = TextTranslationBot(api_key="test-key", target_language="FRA")

        self.assertIn("into French", bot.system_prompt)
        self.assertNotIn("into FRA", bot.system_prompt)

    def test_french_church_links_use_fra_code(self):
        processor = LinkProcessor("FRA", str(APP_DIR), [])
        source = "https://www.churchofjesuschrist.org/study/scriptures/bofm?lang=eng"

        self.assertEqual(
            processor.rewrite_church_links(source),
            "https://www.churchofjesuschrist.org/study/scriptures/bofm?lang=fra",
        )
        self.assertEqual(
            processor.rewrite_church_links(
                "https://www.churchofjesuschrist.org/study/general-conference"
            ),
            "https://www.churchofjesuschrist.org/study/general-conference?lang=fra",
        )

    def test_french_link_mapping_is_persisted_without_losing_other_languages(self):
        source_url = "https://example.test/english"
        french_url = "https://example.test/francais"
        page = self.test_root / "page.html"
        page.write_text(f'<a href="{source_url}">Link</a>', encoding="utf-8")

        processor = LinkProcessor(
            "FRA",
            str(self.test_root),
            [str(page)],
            lambda _url, _context: (french_url, ""),
        )
        processor.pre_process_links(lambda _message: None)

        mapping = json.loads(
            (self.test_root / "link_mapping.json").read_text(encoding="utf-8")
        )
        self.assertEqual(mapping[source_url]["FRA"], french_url)
        self.assertEqual(mapping[source_url]["PTBR"], "")
        self.assertEqual(mapping[source_url]["SPA"], "")

    def test_french_scripture_bot_uses_shipped_french_assets(self):
        bot = ScriptureCheckBot(target_language="FRA", hub_dir=str(REPO_ROOT))

        self.assertEqual(Path(bot.scriptures_path).name, "fra")
        self.assertTrue((Path(bot.scriptures_path) / "bookofmormon.json").is_file())
        self.assertTrue((Path(bot.scriptures_path) / "perlofgreatprice.json").is_file())

    def test_french_xml_flow_localizes_missing_before_translation(self):
        page = self.test_root / "rubric.xml"
        page.write_text("<root><text>Missing work is missing.</text></root>", encoding="utf-8")
        captured = {}
        bot = Mock()

        def translate_xml(content, *_args):
            captured["content"] = content
            return content

        bot.translate_xml_content.side_effect = translate_xml
        controller = TranslationController.__new__(TranslationController)
        controller.target_language = "FRA"
        controller.workspace = Mock()
        controller.workspace.get_target_filepath.return_value = str(page)
        controller._w07_template_paths = set()
        controller.bots = {"xml": bot}
        controller._log = Mock()
        controller._is_already_translated = Mock(return_value=False)
        controller.link_processor = LinkProcessor("FRA", str(APP_DIR), [])
        controller.auditor = Mock()
        controller.auditor.get_relevant_terms.return_value = {}
        controller.scripture_checker = Mock()
        controller.scripture_checker.get_scriptures_for_text.return_value = {}

        controller.process_file(str(page))

        self.assertIn("Non remis work is non remis.", captured["content"])

    def test_french_teaching_notes_title_and_release_notes_are_enforced(self):
        controller = TranslationController.__new__(TranslationController)
        controller.target_language = "FRA"
        controller._log = Mock()
        original = (
            "<html><body><details><summary>Release Notes</summary><div><p>Old</p></div>"
            "</details><details><summary>Course Considerations for Instructor Evaluation"
            "</summary><div><p>Keep in English.</p></div></details></body></html>"
        )

        titled = controller._enforce_teaching_notes_title(
            "<h1>Teaching Notes and Student Outreach</h1><p>Teaching Notes</p>"
        )
        result = controller._apply_teaching_notes_accordion_rules(original, original)

        self.assertIn("Notes pédagogiques et suivi des étudiants", titled)
        self.assertIn("Notes pédagogiques", titled)
        self.assertIn("Notes de version", result)
        self.assertIn("Les notes de version résument", result)
        self.assertIn("Keep in English.", result)


if __name__ == "__main__":
    unittest.main()
