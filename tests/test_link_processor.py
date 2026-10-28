import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.link_processor import LinkProcessor


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


if __name__ == "__main__":
    unittest.main()
