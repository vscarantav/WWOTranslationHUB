import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_repository_manager import GitHubRepositoryManager
from github_translation_controller import GitHubTranslationController, GitHubTranslationRunError


class _RepositoryManager:
    parse_repository_url = staticmethod(GitHubRepositoryManager.parse_repository_url)
    destination_base_name = staticmethod(GitHubRepositoryManager.destination_base_name)
    prepare_translation_tree = staticmethod(GitHubRepositoryManager.prepare_translation_tree)

    def __init__(self):
        self.published = []
        self.clone_branches = []

    def authenticated_user(self):
        return {"login": "personal-user"}

    def choose_destination_name(self, owner, base):
        return base

    def get_pages_configuration(self, owner, repository):
        return {"branch": "live", "path": "/docs", "build_type": "legacy"}

    def clone_source(self, _url, destination, branch=None):
        self.clone_branches.append(branch)
        destination.mkdir(parents=True)
        (destination / "docs").mkdir()
        (destination / "docs" / "README.md").write_text(
            "# Student name\n\nUse this lesson.\n\n```python\nstudent_name = input()\n```\n",
            encoding="utf-8",
        )
        (destination / "unused").mkdir()
        (destination / "unused" / "archive.md").write_text(
            "# This archived source must not be translated.\n",
            encoding="utf-8",
        )
        return {
            "owner": "byui-cse", "repository": "cse340-ww-course-v2",
            "branch": branch or "live", "commit_sha": "a" * 40,
        }

    def publish_translation(self, translated, owner, repository, metadata):
        self.published.append((Path(translated), owner, repository, metadata))
        return {
            "repository_url": f"https://github.com/{owner}/{repository}",
            "pages_url": f"https://{owner}.github.io/{repository}/",
        }


class _Markdown:
    def __init__(self, fail=False):
        self.fail = fail

    def translate(self, content, glossary, page_title):
        if self.fail:
            raise RuntimeError("model failed")
        return content.replace("Student name", "Nome do aluno").replace("Use this lesson", "Use esta lição")


class _Variables:
    def analyze(self, content, extension, page_title, source_file, mapping):
        return [{
            "page_title": page_title,
            "context_summary": "Student input variable",
            "variable_en": "student_name",
            "variable_pt": "nome_aluno",
            "source_file": source_file,
        }]


class _Scriptures:
    def get_scriptures_for_text(self, content):
        return {}


class _Report:
    def __init__(self, root):
        self.path = str(root / "report.xlsx")
        self.calls = []

    def generate(self, name, review, variables, assets):
        self.calls.append((name, review, variables, assets))
        Path(self.path).write_bytes(b"report")
        return self.path


class GitHubTranslationControllerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_github_controller_{uuid.uuid4().hex}"
        (self.root / "Glossary" / "sd_glossaries").mkdir(parents=True)
        (self.root / "Glossary" / "sd_glossaries" / "global-sd-glossary.md").write_text(
            "| English | Portuguese (Brazil) | Context |\n"
            "| --- | --- | --- |\n| Student | Aluno | Education |\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _controller(self, manager, report, fail=False):
        return GitHubTranslationController(
            self.root,
            "unused-token",
            repository_manager=manager,
            report_generator=report,
            bot_factory=lambda: {
                "markdown": _Markdown(fail),
                "variables": _Variables(),
                "scriptures": _Scriptures(),
            },
            max_workers=1,
            log_func=lambda _message: None,
        )

    def test_success_publishes_only_to_new_personal_repository(self):
        manager = _RepositoryManager()
        report = _Report(self.root)
        result = self._controller(manager, report).run(
            "https://github.com/byui-cse/cse340-ww-course-v2"
        )
        self.assertEqual(result.repository_name, "cse340-ww-course-test1-pt")
        self.assertEqual(manager.clone_branches, ["live"])
        self.assertEqual(len(manager.published), 1)
        translated, owner, repository, _metadata = manager.published[0]
        self.assertEqual(owner, "personal-user")
        self.assertEqual(repository, "cse340-ww-course-test1-pt")
        self.assertFalse((translated / ".git").exists())
        self.assertFalse((translated / "docs").exists())
        self.assertFalse((translated / "unused").exists())
        output = (translated / "README.md").read_text(encoding="utf-8")
        self.assertIn("Nome do aluno", output)
        self.assertIn("student_name = input()", output)
        self.assertEqual(report.calls[0][2][0]["variable_en"], "student_name")
        review_row = report.calls[0][1][0]
        self.assertIn("/docs/README.md", review_row["link_en"])
        self.assertTrue(review_row["link_pt"].endswith("/README.md"))

    def test_final_failure_generates_report_but_never_publishes(self):
        manager = _RepositoryManager()
        report = _Report(self.root)
        with self.assertRaises(GitHubTranslationRunError) as raised:
            self._controller(manager, report, fail=True).run(
                "https://github.com/byui-cse/cse340-ww-course-v2"
            )
        self.assertFalse(manager.published)
        self.assertEqual(raised.exception.report_path, report.path)
        self.assertEqual(report.calls[0][1][0]["status"], "Failed")
