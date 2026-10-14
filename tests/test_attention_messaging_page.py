import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from controller import TranslationController


SOURCE_PAGE = """<html>
<head>
<meta name="identifier" content="page-id"/>
<title>Attention: Messaging Instructors and Graders</title>
</head>
<body><p>Original English body.</p></body>
</html>"""


class AttentionMessagingPageTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path.cwd() / "tests" / f"_attention_test_{uuid.uuid4().hex}"
        self.hub_dir = self.test_root / "hub"
        self.output_dir = self.test_root / "course_PTBR"
        self.wiki_dir = self.output_dir / "wiki_content"
        self.common_images_dir = self.hub_dir / "Common Course Images"
        self.wiki_dir.mkdir(parents=True)
        self.common_images_dir.mkdir(parents=True)

        self.page_path = (
            self.wiki_dir / TranslationController.ATTENTION_PAGE_FILENAME
        )
        self.page_path.write_text(SOURCE_PAGE, encoding="utf-8")
        (self.output_dir / "imsmanifest.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">
  <resources>
  </resources>
</manifest>""",
            encoding="utf-8",
        )

        for index, (source_name, _packaged_name) in enumerate(
            TranslationController.ATTENTION_IMAGE_SPECS,
            start=1,
        ):
            (self.common_images_dir / source_name).write_bytes(
                f"image-{index}".encode("ascii")
            )

        self.controller = object.__new__(TranslationController)
        self.controller.target_language = "PTBR"
        self.controller.hub_dir = str(self.hub_dir)
        self.controller.workspace = Mock(output_dir=str(self.output_dir))
        self.controller.workspace.get_target_filepath.side_effect = lambda path: str(path)
        self.controller._log = Mock()
        self.controller._attention_package_prepared = False

    def tearDown(self):
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_packages_images_and_registers_manifest_resources_idempotently(self):
        self.assertTrue(self.controller._prepare_attention_messaging_package())

        media_dir = self.output_dir / "web_resources" / "Uploaded Media"
        for index, (_source_name, packaged_name) in enumerate(
            TranslationController.ATTENTION_IMAGE_SPECS,
            start=1,
        ):
            self.assertEqual(
                (media_dir / packaged_name).read_bytes(),
                f"image-{index}".encode("ascii"),
            )

        manifest_path = self.output_dir / "imsmanifest.xml"
        self.controller._register_attention_images_in_manifest(str(manifest_path))
        manifest = BeautifulSoup(manifest_path.read_text(encoding="utf-8"), "xml")

        for _source_name, packaged_name in TranslationController.ATTENTION_IMAGE_SPECS:
            href = f"web_resources/Uploaded Media/{packaged_name}"
            resources = manifest.find_all("resource", attrs={"href": href})
            self.assertEqual(len(resources), 1)
            self.assertEqual(resources[0].find("file")["href"], href)

    def test_builds_canonical_page_with_portable_image_references(self):
        translated = self.controller._build_attention_messaging_page(SOURCE_PAGE)
        soup = BeautifulSoup(translated, "html.parser")

        self.assertEqual(
            soup.title.get_text(strip=True),
            TranslationController.ATTENTION_PAGE_PTBR_TITLE,
        )
        self.assertEqual(soup.find("meta", attrs={"name": "identifier"})["content"], "page-id")
        self.assertIn("Os avaliadores", soup.body.get_text(" ", strip=True))
        self.assertNotIn("Original English body", translated)
        self.assertNotIn("data-api-endpoint", translated)
        self.assertNotIn("/courses/55972/", translated)

        image_sources = [image["src"] for image in soup.find_all("img")]
        self.assertEqual(
            image_sources,
            [
                "$IMS-CC-FILEBASE$/Uploaded%20Media/"
                "attention-messaging-instructors-graders-ptbr-1.png",
                "$IMS-CC-FILEBASE$/Uploaded%20Media/"
                "attention-messaging-instructors-graders-ptbr-2.png",
            ],
        )

    def test_process_file_bypasses_html_translation_bot(self):
        html_bot = Mock()
        self.controller.bots = {"html": html_bot}

        self.controller.process_file(str(self.page_path))

        html_bot.translate_html_content.assert_not_called()
        html_bot.translate_html_content_in_chunks.assert_not_called()
        translated = self.page_path.read_text(encoding="utf-8")
        self.assertIn("Estudantes que t&ecirc;m d&uacute;vidas", translated)
        self.assertTrue(any(
            "TranslatedPage" in call.args[0]
            for call in self.controller._log.call_args_list
        ))

    def test_missing_common_image_stops_packaging(self):
        missing_name = TranslationController.ATTENTION_IMAGE_SPECS[1][0]
        (self.common_images_dir / missing_name).unlink()

        with self.assertRaisesRegex(FileNotFoundError, missing_name):
            self.controller._prepare_attention_messaging_package()

    def test_spanish_page_is_not_treated_as_the_ptbr_special_case(self):
        self.controller.target_language = "SPA"

        self.assertFalse(
            self.controller._is_attention_messaging_page(
                str(self.page_path),
                SOURCE_PAGE,
            )
        )
        self.assertFalse(self.controller._prepare_attention_messaging_package())


if __name__ == "__main__":
    unittest.main()
