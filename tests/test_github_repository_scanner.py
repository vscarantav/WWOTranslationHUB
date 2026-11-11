import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_repository_scanner import GitHubRepositoryScanner


class GitHubRepositoryScannerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_github_scanner_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_scans_content_and_inventory_assets_deterministically(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "lesson.md").write_text(
            "# Variables\n![Diagram](images/model.png)\n[Worksheet](files/work.pdf)",
            encoding="utf-8",
        )
        (self.root / "docs" / "image.png").write_bytes(b"png")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("ignored", encoding="utf-8")

        scanner = GitHubRepositoryScanner()
        manifest = scanner.scan(self.root)
        self.assertEqual([item.relative_path for item in manifest], [
            "docs/image.png", "docs/lesson.md"
        ])
        self.assertEqual(manifest[1].action, "translate")

        assets = scanner.inventory_assets(self.root, manifest)
        self.assertEqual([asset.asset_path for asset in assets], [
            "images/model.png", "files/work.pdf"
        ])
        self.assertEqual(assets[0].alt_text, "Diagram")

    def test_inventories_external_video_providers_from_embeds_and_links(self):
        lesson = self.root / "lesson.html"
        lesson.write_text(
            '<h1>Videos</h1>'
            '<iframe title="YouTube lesson" src="https://www.youtube.com/embed/abc"></iframe>'
            '<iframe src="https://www.loom.com/embed/def"></iframe>'
            '<iframe src="https://cdnapisec.kaltura.com/p/1/embedIframeJs?entry_id=ghi"></iframe>'
            '<a href="https://media.brightspotcdn.com/video/jkl">BrightSpot video</a>'
            '<a href="https://example.com/ordinary-page">Not a video</a>',
            encoding="utf-8",
        )

        scanner = GitHubRepositoryScanner()
        assets = scanner.extract_assets(lesson, self.root)

        self.assertEqual(len(assets), 5)
        videos = [asset for asset in assets if asset.asset_type == "Video"]
        self.assertEqual(len(videos), 4)
        self.assertTrue(all(asset.external for asset in assets))
        self.assertEqual(
            [scanner.video_provider(asset.asset_path) for asset in videos],
            ["BrightSpot", "YouTube", "Loom", "Kaltura"],
        )
        youtube = next(asset for asset in assets if "youtube" in asset.asset_path)
        self.assertEqual(youtube.alt_text, "YouTube lesson")
        ordinary = next(asset for asset in assets if "ordinary-page" in asset.asset_path)
        self.assertEqual(ordinary.asset_type, "Link")

    def test_inventories_codepen_links_and_embeds(self):
        lesson = self.root / "lesson.html"
        lesson.write_text(
            '<a href="https://codepen.io/example/pen/abc">CodePen example</a>'
            '<iframe src="https://codepen.io/example/embed/def"></iframe>',
            encoding="utf-8",
        )

        scanner = GitHubRepositoryScanner()
        assets = scanner.extract_assets(lesson, self.root)

        self.assertEqual(len(assets), 2)
        self.assertTrue(all(asset.asset_type == "Codepen" for asset in assets))
        self.assertTrue(all(scanner.is_codepen(asset.asset_path) for asset in assets))

    def test_inventories_public_links_but_excludes_local_development_links(self):
        lesson = self.root / "lesson.html"
        lesson.write_text(
            '<a href="https://github.com/byui-cse/course">Repository</a>'
            '<a href="https://school.instructure.com/courses/123">Canvas</a>'
            '<a href="https://example.org/reference">Reference</a>'
            '<a href="http://localhost:3000/api">Localhost</a>'
            '<a href="http://127.0.0.1:3000/api">Loopback</a>'
            '<a href="week02.html">Internal navigation</a>'
            '<a href="#details">Page fragment</a>',
            encoding="utf-8",
        )

        scanner = GitHubRepositoryScanner()
        assets = scanner.extract_assets(lesson, self.root)

        self.assertEqual(
            [asset.asset_path for asset in assets],
            [
                "https://github.com/byui-cse/course",
                "https://school.instructure.com/courses/123",
                "https://example.org/reference",
            ],
        )
        self.assertTrue(scanner.is_github(assets[0].asset_path))
        self.assertTrue(scanner.is_canvas(assets[1].asset_path))
        self.assertFalse(scanner.is_github(assets[2].asset_path))
        self.assertFalse(scanner.is_canvas(assets[2].asset_path))

    def test_maps_css_image_to_each_page_that_uses_its_selector(self):
        (self.root / "styles").mkdir()
        (self.root / "images").mkdir()
        (self.root / "week01").mkdir()
        (self.root / "styles" / "course.css").write_text(
            ".disciples { background-image: url(../images/disciples.png); }",
            encoding="utf-8",
        )
        (self.root / "images" / "disciples.png").write_bytes(b"png")
        (self.root / "week01" / "lesson.html").write_text(
            '<html><head><title>Lesson</title>'
            '<link rel="stylesheet" href="../styles/course.css"></head>'
            '<body><div class="callout disciples">Visible callout</div></body></html>',
            encoding="utf-8",
        )
        (self.root / "week01" / "unused.html").write_text(
            '<html><head><title>Unused</title>'
            '<link rel="stylesheet" href="../styles/course.css"></head>'
            '<body><p>No matching class</p></body></html>',
            encoding="utf-8",
        )

        scanner = GitHubRepositoryScanner()
        assets = scanner.inventory_assets(self.root)

        css_asset = next(
            asset for asset in assets if asset.asset_path == "/images/disciples.png"
        )
        self.assertEqual(css_asset.source_file, "week01/lesson.html")
        self.assertEqual(css_asset.page_title, "Lesson")
        self.assertEqual(css_asset.asset_type, "Image")
        self.assertEqual(css_asset.css_selector, ".disciples")
        self.assertFalse(any(asset.source_file == "week01/unused.html" for asset in assets))
