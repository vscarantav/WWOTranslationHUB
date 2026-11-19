import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.xml_bot import XMLTranslationBot
from controller import TranslationController


SOURCE_BANK = """<?xml version="1.0" encoding="UTF-8"?>
<questestinterop>
  <objectbank ident="bank1" title="English Bank Attribute">
    <qtimetadata><qtimetadatafield>
      <fieldlabel>bank_title</fieldlabel>
      <fieldentry>QB: W05 English Bank</fieldentry>
    </qtimetadatafield></qtimetadata>
    <item ident="item1" title="Question">
      <presentation><material><mattext>What is a table?</mattext></material></presentation>
    </item>
    <item ident="item2" title="Question">
      <presentation><material><mattext>=AND(C5&gt;=Minimum, C5&lt;=Maximum)</mattext></material></presentation>
    </item>
  </objectbank>
</questestinterop>
"""


def bank_title(content):
    soup = BeautifulSoup(content, "xml")
    for field_entry in soup.find_all("fieldentry"):
        label = field_entry.find_previous_sibling("fieldlabel")
        if label and label.get_text(strip=True) == "bank_title":
            return field_entry.get_text()
    return None


class QuestionBankNamePreservationTests(unittest.TestCase):
    def test_xml_agent_does_not_submit_bank_names_for_translation(self):
        bot = XMLTranslationBot(api_key="test-key")
        submitted = {}

        def translate(items, *_args, **_kwargs):
            submitted.update(items)
            return {key: f"PT: {value}" for key, value in items.items()}

        bot.translate_text_items = translate

        translated = bot.translate_xml_content(SOURCE_BANK, page_title="bank.qti")
        soup = BeautifulSoup(translated, "xml")

        self.assertEqual(bank_title(translated), "QB: W05 English Bank")
        self.assertEqual(
            soup.find("objectbank").get("title"),
            "English Bank Attribute",
        )
        self.assertEqual(soup.find("item").get("title"), "PT: Question")
        self.assertNotIn("QB: W05 English Bank", submitted.values())
        self.assertNotIn("English Bank Attribute", submitted.values())
        self.assertNotIn("=AND(C5&gt;=Minimum, C5&lt;=Maximum)", submitted.values())
        self.assertEqual(
            soup.find_all("mattext")[1].get_text(),
            "=AND(C5>=Minimum, C5<=Maximum)",
        )

    def test_controller_restores_existing_translated_bank_name_from_source(self):
        translated_bank = SOURCE_BANK.replace(
            "QB: W05 English Bank",
            "BP: Banco S05",
        )
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            output_dir = Path(temp_dir) / "course_PTBR"
            target = output_dir / "non_cc_assessments" / "bank.xml.qti"
            target.parent.mkdir(parents=True)
            target.write_text(translated_bank, encoding="utf-8")

            controller = TranslationController.__new__(TranslationController)
            controller.workspace = Mock(
                output_dir=str(output_dir),
                _read_source_text=Mock(return_value=SOURCE_BANK),
            )
            logs = []
            controller._log = logs.append

            restored = controller._preserve_question_bank_titles()

            self.assertEqual(restored, 1)
            self.assertEqual(
                bank_title(target.read_text(encoding="utf-8")),
                "QB: W05 English Bank",
            )
            self.assertTrue(any("restored 1" in message for message in logs))


if __name__ == "__main__":
    unittest.main()
