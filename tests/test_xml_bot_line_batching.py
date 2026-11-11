import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.xml_bot import XML_BATCH_MAX_LINES, XMLTranslationBot


class XmlBotLineBatchingTests(unittest.TestCase):
    def test_splits_one_multiline_node_into_600_line_packages(self):
        content = "\n".join(f"Line {index}" for index in range(1201))

        batches, source_chunks = XMLTranslationBot._build_line_limited_batches(
            {"0": content}
        )

        self.assertEqual(
            [
                sum(
                    XMLTranslationBot._content_line_count(value)
                    for value in batch.values()
                )
                for batch in batches
            ],
            [600, 600, 1],
        )
        self.assertEqual(len(source_chunks["0"]), 3)

    def test_every_package_stays_within_600_lines_for_many_nodes(self):
        items = {
            str(index): f"Question {index}\nAnswer {index}"
            for index in range(1000)
        }

        batches, _ = XMLTranslationBot._build_line_limited_batches(items)

        self.assertGreater(len(batches), 1)
        self.assertEqual(sum(len(batch) for batch in batches), len(items))
        self.assertTrue(
            all(
                sum(
                    XMLTranslationBot._content_line_count(value)
                    for value in batch.values()
                )
                <= XML_BATCH_MAX_LINES
                for batch in batches
            )
        )

    def test_reassembles_a_node_split_across_packages(self):
        source_lines = [f"English line {index}" for index in range(605)]
        xml = "<root><description><![CDATA[" + "\n".join(source_lines) + "]]></description></root>"
        bot = XMLTranslationBot(api_key="test-key")
        bot._log = Mock()
        observed_line_counts = []

        def translate(batch, _constraints):
            observed_line_counts.append(
                sum(bot._content_line_count(value) for value in batch.values())
            )
            return {
                item_id: value.replace("English", "Translated")
                for item_id, value in batch.items()
            }

        bot._translate_batch = Mock(side_effect=translate)

        translated = bot.translate_xml_content(xml)

        self.assertEqual(observed_line_counts, [600, 5])
        self.assertEqual(translated.count("Translated line"), 605)
        self.assertNotIn("English line", translated)

    def test_translate_batch_rejects_an_oversized_payload(self):
        bot = XMLTranslationBot(api_key="test-key")
        bot._log = Mock()
        oversized_content = "\n".join(
            f"Line {index}" for index in range(XML_BATCH_MAX_LINES + 1)
        )

        with self.assertRaisesRegex(ValueError, "600-line limit"):
            bot._translate_batch({"0": oversized_content}, "")


if __name__ == "__main__":
    unittest.main()
