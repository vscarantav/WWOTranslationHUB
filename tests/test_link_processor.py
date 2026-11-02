import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.link_processor import LinkMappingPersistenceError, LinkProcessor


class LinkProcessorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_link_processor_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_rewrites_only_exact_byui_course_repository_suffix(self):
        page = self.root / "page.html"
        page.write_text(
            '<a href="https://byui-cse.github.io/cse111-course/week01/">Course</a>'
            '<a href="https://byui-cse.github.io/cse340-ww-course-v2/week01/">V2</a>',
            encoding="utf-8",
        )
        prompted_urls = []

        def prompt(url, _context):
            prompted_urls.append(url)
            return None

        processor = LinkProcessor("PTBR", str(self.root), [str(page)], prompt)

        processor.pre_process_links(lambda _message: None)

        result = page.read_text(encoding="utf-8")
        self.assertIn("/cse111-course-pt/week01/", result)
        self.assertIn("/cse340-ww-course-v2/week01/", result)
        self.assertNotIn("cse340-ww-course-v2-pt", result)
        self.assertNotIn(
            "https://byui-cse.github.io/cse111-course-pt/week01/",
            prompted_urls,
        )

    def test_logs_persisted_mapping_replacements(self):
        source_url = "https://example.com/english"
        target_url = "https://example.com/portugues"
        page = self.root / "page.html"
        page.write_text(
            f'<html><head><title>Welcome</title></head><body><a href="{source_url}">Link</a></body></html>',
            encoding="utf-8",
        )
        (self.root / "link_mapping.json").write_text(
            '{\n'
            f'  "{source_url}": {{\n'
            f'    "PTBR": "{target_url}",\n'
            '    "SPA": ""\n'
            '  }\n'
            '}',
            encoding="utf-8",
        )
        messages = []
        processor = LinkProcessor("PTBR", str(self.root), [str(page)])

        processor.pre_process_links(messages.append)

        self.assertIn(target_url, page.read_text(encoding="utf-8"))
        self.assertIn(
            f"[LinkBot] MappedLink: Welcome (page.html),{source_url},{target_url}",
            messages,
        )

    def test_overlapping_flows_preserve_every_user_added_pt_link(self):
        first_source = "https://example.com/english-one"
        first_target = "https://example.com/portugues-um"
        second_source = "https://example.com/english-two"
        second_target = "https://example.com/portugues-dois"
        first_page = self.root / "first.html"
        second_page = self.root / "second.html"
        first_page.write_text(
            f'<a href="{first_source}">First</a>',
            encoding="utf-8",
        )
        second_page.write_text(
            f'<a href="{second_source}">Second</a>',
            encoding="utf-8",
        )

        second_processor = LinkProcessor(
            "PTBR",
            str(self.root),
            [str(second_page)],
            lambda _url, _context: (second_target, ""),
        )

        def first_prompt(_url, _context):
            # Model a second mapping flow saving while the first flow still
            # holds the mapping snapshot it loaded at startup.
            second_processor.pre_process_links(lambda _message: None)
            return first_target, ""

        first_processor = LinkProcessor(
            "PTBR",
            str(self.root),
            [str(first_page)],
            first_prompt,
        )

        first_processor.pre_process_links(lambda _message: None)

        saved_mapping = json.loads(
            (self.root / "link_mapping.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved_mapping[first_source]["PTBR"], first_target)
        self.assertEqual(saved_mapping[second_source]["PTBR"], second_target)

    def test_mapping_write_failure_is_logged_and_stops_processing(self):
        source_url = "https://example.com/english"
        target_url = "https://example.com/portugues"
        page = self.root / "page.html"
        page.write_text(
            f'<a href="{source_url}">Link</a>',
            encoding="utf-8",
        )
        messages = []
        processor = LinkProcessor(
            "PTBR",
            str(self.root),
            [str(page)],
            lambda _url, _context: (target_url, ""),
        )

        with patch(
            "core.link_processor.os.replace",
            side_effect=OSError("write denied"),
        ):
            with self.assertRaises(LinkMappingPersistenceError):
                processor.pre_process_links(messages.append)

        self.assertTrue(
            any("[LinkBot] MappingSaveFailed:" in message for message in messages)
        )
        self.assertEqual(
            list(self.root.glob(".link_mapping_*.tmp")),
            [],
        )


if __name__ == "__main__":
    unittest.main()
