import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.workspace_manager import WorkspaceManager


def write_imscc(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


class WorkspaceManagerCourseInfoTests(unittest.TestCase):
    def test_context_course_id_wins_over_mixed_embedded_course_links(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            package = Path(temp_dir) / "course.imscc"
            write_imscc(
                package,
                {
                    "imsmanifest.xml": "<manifest><title>Course</title></manifest>",
                    "course_settings/context.xml": (
                        "<context_info><course_id>354</course_id>"
                        "<canvas_domain>example.instructure.com</canvas_domain></context_info>"
                    ),
                    "wiki_content/first.html": (
                        '<img data-api-endpoint="https://example.instructure.com/'
                        'api/v1/courses/193974/files/1">'
                    ),
                    "wiki_content/second.html": (
                        '<img data-api-endpoint="https://example.instructure.com/'
                        'api/v1/courses/244188/files/2">'
                    ),
                },
            )

            manager = WorkspaceManager("PTBR", temp_dir, imscc_path=str(package))
            manager.extract_course_info(lambda _message: None)

            self.assertEqual(manager.source_course_id, "354")
            self.assertEqual(manager.source_course_id_source, "context.xml")
            self.assertEqual(manager.source_course_id_candidates, ["193974", "244188"])
            self.assertEqual(manager.canvas_url, "https://example.instructure.com")

    def test_legacy_package_uses_one_consistent_embedded_course_id(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            package = Path(temp_dir) / "legacy.imscc"
            write_imscc(
                package,
                {
                    "wiki_content/one.html": (
                        "<img data-api-endpoint='https://example.instructure.com/"
                        "api/v1/courses/42/files/1'>"
                    ),
                    "wiki_content/two.html": (
                        '<a data-api-endpoint="https://example.instructure.com/'
                        'api/v1/courses/42/modules">Modules</a>'
                    ),
                },
            )

            manager = WorkspaceManager("SPA", temp_dir, imscc_path=str(package))
            manager.extract_course_info(lambda _message: None)

            self.assertEqual(manager.source_course_id, "42")
            self.assertEqual(manager.source_course_id_source, "wiki endpoints")

    def test_legacy_package_with_mixed_ids_defers_to_entered_url(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            package = Path(temp_dir) / "ambiguous.imscc"
            write_imscc(
                package,
                {
                    "wiki_content/one.html": (
                        '<img data-api-endpoint="https://example.instructure.com/'
                        'api/v1/courses/10/files/1">'
                    ),
                    "wiki_content/two.html": (
                        '<img data-api-endpoint="https://example.instructure.com/'
                        'api/v1/courses/20/files/2">'
                    ),
                },
            )
            logs = []

            manager = WorkspaceManager("PTBR", temp_dir, imscc_path=str(package))
            manager.extract_course_info(logs.append)

            self.assertIsNone(manager.source_course_id)
            self.assertEqual(manager.source_course_id_candidates, ["10", "20"])
            self.assertTrue(any("Multiple course IDs" in message for message in logs))

    def test_setup_replaces_stale_source_and_output_directories(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            hub_dir = Path(temp_dir)
            courses_dir = hub_dir / "Courses to Translate"
            courses_dir.mkdir()
            package = courses_dir / "course.imscc"
            write_imscc(package, {"imsmanifest.xml": "<manifest />", "version.txt": "new"})

            stale_source = courses_dir / "course"
            stale_output = courses_dir / "course_PTBR"
            stale_source.mkdir()
            stale_output.mkdir()
            (stale_source / "stale.txt").write_text("old", encoding="utf-8")
            (stale_output / "stale.txt").write_text("old", encoding="utf-8")

            manager = WorkspaceManager("PTBR", str(hub_dir), imscc_path=str(package))
            self.assertTrue(manager.setup_workspace("unused"))

            self.assertFalse((stale_source / "stale.txt").exists())
            self.assertFalse((stale_output / "stale.txt").exists())
            self.assertEqual((stale_source / "version.txt").read_text(), "new")
            self.assertEqual((stale_output / "version.txt").read_text(), "new")


if __name__ == "__main__":
    unittest.main()
