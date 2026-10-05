import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_repository_manager import GitHubRepositoryError, GitHubRepositoryManager


class GitHubRepositoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path.cwd() / "tests" / f"_github_manager_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_url_and_testing_name_follow_approved_convention(self):
        self.assertEqual(
            GitHubRepositoryManager.parse_repository_url(
                "https://github.com/byui-cse/cse340-ww-course-v2.git"
            ),
            ("byui-cse", "cse340-ww-course-v2"),
        )
        self.assertEqual(
            GitHubRepositoryManager.destination_base_name("cse340-ww-course-v2"),
            "cse340-ww-course-test1-pt",
        )

    def test_github_pages_url_resolves_to_canonical_clone_url(self):
        pages_url = "https://byui-cse.github.io/cse340-ww-course-v2/index.html"
        self.assertEqual(
            GitHubRepositoryManager.parse_repository_url(pages_url),
            ("byui-cse", "cse340-ww-course-v2"),
        )
        self.assertEqual(
            GitHubRepositoryManager.canonical_repository_url(pages_url),
            "https://github.com/byui-cse/cse340-ww-course-v2.git",
        )

        commands = []

        def git_runner(command, cwd, authenticate):
            commands.append((command, cwd, authenticate))
            if command[1:3] == ["branch", "--show-current"]:
                return "main"
            if command[1:3] == ["rev-parse", "HEAD"]:
                return "a" * 40
            return ""

        manager = GitHubRepositoryManager("token", git_runner=git_runner)
        manager.clone_source(pages_url, self.temp_dir / "source")
        clone_command = commands[0][0]
        self.assertIn("https://github.com/byui-cse/cse340-ww-course-v2.git", clone_command)
        self.assertNotIn(pages_url, clone_command)

    def test_numbered_name_never_reuses_an_existing_repository(self):
        manager = GitHubRepositoryManager("token")
        manager.repository_exists = lambda _owner, repo: repo in {
            "course-test1-pt", "course-test1-pt-2"
        }
        self.assertEqual(
            manager.choose_destination_name("personal-user", "course-test1-pt"),
            "course-test1-pt-3",
        )
        with self.assertRaises(GitHubRepositoryError):
            manager.choose_destination_name("byui-cse", "unsafe")

    def test_translation_tree_has_no_source_git_or_workflows(self):
        source = self.temp_dir / "source"
        (source / ".git").mkdir(parents=True)
        (source / ".git" / "config").write_text("secret", encoding="utf-8")
        (source / ".github" / "workflows").mkdir(parents=True)
        (source / ".github" / "workflows" / "deploy.yml").write_text("run", encoding="utf-8")
        (source / "docs").mkdir()
        (source / "docs" / "index.md").write_text("# Course", encoding="utf-8")

        destination = self.temp_dir / "translated"
        GitHubRepositoryManager.prepare_translation_tree(source, destination)

        self.assertFalse((destination / ".git").exists())
        self.assertFalse((destination / ".github" / "workflows").exists())
        self.assertTrue((destination / "docs" / "index.md").is_file())
