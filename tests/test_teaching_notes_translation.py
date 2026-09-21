import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.html_bot import HTMLTranslationBot
from controller import TranslationController


class TeachingNotesChunkTranslationTests(unittest.TestCase):
    def test_detects_a_long_english_node_left_unchanged(self):
        self.assertTrue(HTMLTranslationBot._is_unchanged_english_text(
            "You will write the final project in this course.",
            "You will write the final project in this course.",
        ))
        self.assertFalse(HTMLTranslationBot._is_unchanged_english_text(
            "You will write the final project in this course.",
            "Você escreverá o projeto final deste curso.",
        ))
        self.assertFalse(HTMLTranslationBot._is_unchanged_english_text(
            "BYU Idaho",
            "BYU Idaho",
        ))
        self.assertFalse(HTMLTranslationBot._is_unchanged_english_text(
            "https://www.byui.edu/speeches/i-will-not-remove-mine-integrity-from-me",
            "https://www.byui.edu/speeches/i-will-not-remove-mine-integrity-from-me",
        ))

    def test_translates_visible_text_nodes_without_changing_html_attributes(self):
        bot = HTMLTranslationBot(api_key="test-key", target_language="PTBR")
        bot._log = Mock()
        bot._translate_text_batch = Mock(
            side_effect=lambda batch, _constraints: {
                item_id: f"PT: {text}"
                for item_id, text in batch.items()
            }
        )
        source = (
            '<div class="content"><h1>Teaching Notes and Student Outreach</h1>'
            '<p>Purpose <strong>Support students</strong></p>'
            '<a href="https://example.com/path">Open resource</a>'
            '<script>Do not translate this</script></div>'
        )

        translated = bot.translate_html_content_in_chunks(
            source,
            relevant_glossary={
                "Teaching Notes and Student Outreach": "Plano de Aula e de Contato Com Os Estudantes"
            },
            page_title="Teaching Notes and Student Outreach",
            batch_limit=80,
        )

        soup = BeautifulSoup(translated, "html.parser")
        self.assertEqual(soup.a["href"], "https://example.com/path")
        self.assertEqual(soup.script.string, "Do not translate this")
        self.assertEqual(soup.h1.get_text(), "PT: Teaching Notes and Student Outreach")
        self.assertEqual(soup.strong.get_text(), "PT: Support students")
        self.assertGreater(bot._translate_text_batch.call_count, 1)

    def test_ignores_clipboard_comments_and_preserves_space_after_strong(self):
        bot = HTMLTranslationBot(api_key="test-key", target_language="PTBR")
        bot._log = Mock()

        translations = {
            "Purpose:": "Objetivo:",
            "To practice writing effective prompts.": "Praticar a escrita de prompts eficazes.",
            "Length": "Tamanho",
            ": Two responses": ": Duas respostas",
        }
        seen_source_text = []

        def translate(batch, _constraints):
            seen_source_text.extend(batch.values())
            return {
                item_id: translations[text]
                for item_id, text in batch.items()
            }

        bot._translate_text_batch = Mock(side_effect=translate)
        source = (
            '<ul><li><!--StartFragment--><strong>Purpose:</strong>\n'
            'To practice writing effective prompts.<!--EndFragment--></li>'
            '<li><strong>Length</strong>\n: Two responses</li></ul>'
        )

        translated = bot.translate_html_content_in_chunks(source)

        self.assertNotIn("StartFragment", translated)
        self.assertNotIn("EndFragment", translated)
        self.assertNotIn("StartFragment", seen_source_text)
        self.assertNotIn("EndFragment", seen_source_text)
        self.assertIn("</strong> Praticar", translated)
        self.assertIn("</strong>: Duas", translated)

    def test_rejects_an_unchanged_english_page(self):
        bot = HTMLTranslationBot(api_key="test-key", target_language="PTBR")
        bot._log = Mock()
        bot._translate_text_batch = Mock(side_effect=lambda batch, _constraints: dict(batch))

        with self.assertRaisesRegex(RuntimeError, "unchanged in English"):
            bot.translate_html_content_in_chunks(
                "<h1>Teaching Notes and Student Outreach</h1><p>Support students.</p>"
            )


class TeachingNotesTitleTests(unittest.TestCase):
    def test_recognizes_legacy_and_short_teaching_notes_filenames(self):
        controller = object.__new__(TranslationController)

        self.assertTrue(controller._is_teaching_notes_page(
            "wiki_content/teaching-notes-and-student-outreach.html"
        ))
        self.assertTrue(controller._is_teaching_notes_page(
            "wiki_content/teaching-notes.html"
        ))
        self.assertFalse(controller._is_teaching_notes_page(
            "web_resources/teaching-notes-update.png"
        ))

    def test_enforces_portuguese_title_in_page_and_module_metadata(self):
        controller = object.__new__(TranslationController)
        controller.target_language = "PTBR"
        content = (
            "<module><item><title>Teaching Notes and Student Outreach</title>"
            "</item></module>"
        )

        translated = controller._enforce_teaching_notes_title(content)

        self.assertNotIn("Teaching Notes and Student Outreach", translated)
        self.assertIn("Plano de Aula e de Contato Com Os Estudantes", translated)

    def test_enforces_short_title_without_replacing_normal_prose(self):
        controller = object.__new__(TranslationController)
        controller.target_language = "PTBR"
        content = (
            '<item title="Teaching Notes"><title>Teaching Notes</title></item>'
            '<p>Review the Teaching Notes before class.</p>'
        )

        translated = controller._enforce_teaching_notes_title(content)

        self.assertIn('title="Notas de Ensino"', translated)
        self.assertIn("<title>Notas de Ensino</title>", translated)
        self.assertIn("Review the Teaching Notes before class.", translated)


class TranslationFailurePropagationTests(unittest.TestCase):
    def test_worker_failure_stops_package_creation_path(self):
        controller = object.__new__(TranslationController)
        controller.filepaths = ["good.html", "teaching-notes-and-student-outreach.html"]
        controller._log = Mock()
        controller.workspace = Mock(imscc_path="course.imscc")

        def process_file(filepath):
            if "teaching-notes" in filepath:
                raise RuntimeError("unchanged in English")

        controller.process_file = process_file

        with self.assertRaisesRegex(RuntimeError, "IMSCC package was not created"):
            controller.translate_files()

        retry_failure_logs = [
            call
            for call in controller._log.call_args_list
            if "Retry failed" in call.args[0]
        ]
        self.assertEqual(len(retry_failure_logs), 1)

        self.assertTrue(any(
            "unchanged in English" in call.args[0]
            for call in controller._log.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
