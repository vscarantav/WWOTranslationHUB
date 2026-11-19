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

    def test_repackaging_restores_exact_source_member_names_and_collisions(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            hub_dir = Path(temp_dir)
            courses_dir = hub_dir / "Courses to Translate"
            courses_dir.mkdir()
            package = courses_dir / "course.imscc"
            write_imscc(
                package,
                {
                    "imsmanifest.xml": (
                        "<manifest><resources><resource>"
                        '<file href="assets/name:one.txt"/>'
                        '<file href="assets/Gateway.png"/>'
                        '<file href="assets/gateway.png"/>'
                        '<file href="content.html"/>'
                        "</resource></resources></manifest>"
                    ),
                    "assets/name:one.txt": "colon asset",
                    "assets/Gateway.png": "upper asset",
                    "assets/gateway.png": "lower asset",
                    "content.html": "English source",
                },
            )

            manager = WorkspaceManager("PTBR", str(hub_dir), imscc_path=str(package))
            self.assertTrue(manager.setup_workspace("unused"))
            (Path(manager.output_dir) / "content.html").write_text(
                "Conteúdo traduzido",
                encoding="utf-8",
            )

            output = manager.compress_to_imscc(lambda _message: None)

            with zipfile.ZipFile(output, "r") as archive:
                names = set(archive.namelist())
                self.assertIn("assets/name:one.txt", names)
                self.assertIn("assets/Gateway.png", names)
                self.assertIn("assets/gateway.png", names)
                self.assertEqual(archive.read("assets/Gateway.png"), b"upper asset")
                self.assertEqual(archive.read("assets/gateway.png"), b"lower asset")
                self.assertEqual(
                    archive.read("content.html").decode("utf-8"),
                    "Conteúdo traduzido",
                )

    def test_repackaging_fails_when_manifest_member_is_missing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            output_dir = Path(temp_dir) / "course_PTBR"
            output_dir.mkdir()
            (output_dir / "imsmanifest.xml").write_text(
                "<manifest><resources><resource>"
                '<file href="missing.html"/>'
                "</resource></resources></manifest>",
                encoding="utf-8",
            )
            manager = WorkspaceManager("PTBR", temp_dir)
            manager.output_dir = str(output_dir)

            with self.assertRaisesRegex(
                RuntimeError,
                "missing manifest-referenced member",
            ):
                manager.compress_to_imscc(lambda _message: None)


if __name__ == "__main__":
    unittest.main()
