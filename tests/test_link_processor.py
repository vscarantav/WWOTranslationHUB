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
        processor = LinkProcessor("PTBR", str(self.root), [str(page)])

        processor.pre_process_links(lambda _message: None)

        result = page.read_text(encoding="utf-8")
        self.assertIn("/cse111-course-pt/week01/", result)
        self.assertIn("/cse340-ww-course-v2/week01/", result)
        self.assertNotIn("cse340-ww-course-v2-pt", result)


if __name__ == "__main__":
    unittest.main()
