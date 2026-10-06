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

        self.assertEqual(len(assets), 4)
        self.assertTrue(all(asset.asset_type == "Video" for asset in assets))
        self.assertTrue(all(asset.external for asset in assets))
        self.assertEqual(
            [scanner.video_provider(asset.asset_path) for asset in assets],
            ["BrightSpot", "YouTube", "Loom", "Kaltura"],
        )
        youtube = next(asset for asset in assets if "youtube" in asset.asset_path)
        self.assertEqual(youtube.alt_text, "YouTube lesson")
