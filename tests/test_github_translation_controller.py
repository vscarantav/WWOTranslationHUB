import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_repository_manager import GitHubRepositoryManager
from core.github_repository_scanner import AssetReference, GitHubRepositoryScanner
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
        (destination / "docs" / "reference.md").write_text(
            "# Reference\n\n```python\nprint(student_name)\n```\n",
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
        if "student_name =" not in content:
            return []
        return [{
            "page_title": page_title,
            "context_summary": "Student input variable",
            "variable_en": "student_name",
            "variable_pt": "nome_aluno",
            "source_file": source_file,
        }]


class _ProtectedIdentifierVariables:
    MAPPING = {
        "NODE_ENV": "AMBIENTE_NODE",
        "PORT": "PORTA",
        "DATABASE_URL": "URL_BANCO_DADOS",
        "__filename": "__nome_arquivo",
        "__dirname": "__nome_diretorio",
        "message": "mensagem",
    }

    def analyze(self, content, extension, page_title, source_file, mapping):
        rows = []
        for original, translated in self.MAPPING.items():
            if original not in content:
                continue
            rows.append({
                "page_title": page_title,
                "context_summary": f"Example identifier {original}",
                "variable_en": original,
                "variable_pt": translated,
                "source_file": source_file,
            })
        return rows


class _APISettings:
    def analyze(self, content, extension, page_title, source_file):
        return [{
            "page_title": page_title,
            "source_file": source_file,
            "provider": "Render",
            "setting": "Build Command",
            "value": "npm install && npm run build",
            "context_summary": "Configuração da implantação.",
            "package": "API Setting",
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
        (self.root / "Glossary" / "glossary.json").write_text(
            '{"Student": {"PTBR": "Estudante geral"}}',
            encoding="utf-8",
        )
        (self.root / "Glossary" / "sd_glossaries" / "global-sd-glossary.md").write_text(
            "| English | Portuguese (Brazil) | Context |\n"
            "| --- | --- | --- |\n| Student | Aluno | Education |\n",
            encoding="utf-8",
        )
        self.course_glossary = self.root / "course-glossary.md"
        self.course_glossary.write_text(
            "| English Term | PT-BR Translation | Context |\n"
            "| --- | --- | --- |\n"
            "| Student | Estudante do curso | Course terminology |\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _controller(
        self,
        manager,
        report,
        fail=False,
        progress_func=None,
        variable_bot=None,
    ):
        return GitHubTranslationController(
            self.root,
            "unused-token",
            "personal-user",
            repository_manager=manager,
            report_generator=report,
            bot_factory=lambda: {
                "markdown": _Markdown(fail),
                "variables": variable_bot or _Variables(),
                "api_settings": _APISettings(),
                "scriptures": _Scriptures(),
            },
            max_workers=1,
            log_func=lambda _message: None,
            progress_func=progress_func,
        )

    def test_protects_runtime_identifiers_and_applies_ordinary_variable_pt(self):
        manager = _RepositoryManager()
        original_clone_source = manager.clone_source

        def clone_with_runtime_identifiers(url, destination, branch=None):
            metadata = original_clone_source(url, destination, branch=branch)
            (destination / "docs" / "README.md").write_text(
                "# Student name\n\nUse this lesson.\n\n"
                "```javascript\n"
                "const NODE_ENV = process.env.NODE_ENV || 'production';\n"
                "const PORT = process.env.PORT || 3000;\n"
                "const DATABASE_URL = process.env.DATABASE_URL;\n"
                "const __filename = fileURLToPath(import.meta.url);\n"
                "const __dirname = path.dirname(__filename);\n"
                "let message = 'Ready';\n"
                "console.log(message);\n"
                "```\n",
                encoding="utf-8",
            )
            return metadata

        manager.clone_source = clone_with_runtime_identifiers
        report = _Report(self.root)

        self._controller(
            manager,
            report,
            variable_bot=_ProtectedIdentifierVariables(),
        ).run(
            "https://github.com/byui-cse/cse340-ww-course-v2",
            course_glossary_path=self.course_glossary,
        )

        translated_root = manager.published[0][0]
        output = (translated_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("const NODE_ENV = process.env.NODE_ENV", output)
        self.assertIn("const PORT = process.env.PORT", output)
        self.assertIn("const DATABASE_URL = process.env.DATABASE_URL", output)
        self.assertIn("const __filename = fileURLToPath", output)
        self.assertIn("const __dirname = path.dirname(__filename)", output)
        self.assertIn("let mensagem = 'Ready'", output)
        self.assertIn("console.log(mensagem)", output)
        self.assertNotIn("let message =", output)

        reported_mapping = {
            row["variable_en"]: row["variable_pt"]
            for row in report.calls[0][2]
        }
        reported_rows = {
            row["variable_en"]: row
            for row in report.calls[0][2]
        }
        self.assertEqual(reported_mapping["NODE_ENV"], "NODE_ENV")
        self.assertEqual(reported_mapping["PORT"], "PORT")
        self.assertEqual(reported_mapping["DATABASE_URL"], "DATABASE_URL")
        self.assertEqual(reported_mapping["__filename"], "__filename")
        self.assertEqual(reported_mapping["__dirname"], "__dirname")
        self.assertEqual(reported_mapping["message"], "mensagem")
        self.assertIn(
            "Protected identifier kept unchanged",
            reported_rows["NODE_ENV"]["context_summary"],
        )

    def test_success_publishes_only_to_new_personal_repository(self):
        manager = _RepositoryManager()
        report = _Report(self.root)
        progress = []
        result = self._controller(manager, report, progress_func=progress.append).run(
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
        self.assertIn("nome_aluno = input()", output)
        self.assertNotIn("student_name = input()", output)
        reference_output = (translated / "reference.md").read_text(encoding="utf-8")
        self.assertIn("print(nome_aluno)", reference_output)
        self.assertNotIn("print(student_name)", reference_output)
        self.assertEqual(report.calls[0][2][0]["variable_en"], "student_name")
        self.assertEqual(report.calls[0][2][0]["variable_pt"], "nome_aluno")
        api_setting = report.calls[0][3][0]
        self.assertEqual(
            api_setting["asset_path"],
            "API Setting — Render: Build Command = npm install && npm run build",
        )
        self.assertTrue(api_setting["resource_link"].endswith("/README.md"))
        self.assertTrue(
            api_setting["target_language_link"].endswith("/README.md")
        )
        self.assertEqual(api_setting["package"], "API Setting")
        review_row = report.calls[0][1][0]
        self.assertIn("/docs/README.md", review_row["link_en"])
        self.assertTrue(review_row["link_pt"].endswith("/README.md"))
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 100)
        self.assertEqual(progress, sorted(progress))

    def test_final_failure_generates_report_but_never_publishes(self):
        manager = _RepositoryManager()
        report = _Report(self.root)
        with self.assertRaises(GitHubTranslationRunError) as raised:
            self._controller(manager, report, fail=True).run(
                "https://github.com/byui-cse/cse340-ww-course-v2",
                course_glossary_path=self.course_glossary,
            )
        self.assertFalse(manager.published)
        self.assertEqual(raised.exception.report_path, report.path)
        self.assertEqual(report.calls[0][1][0]["status"], "Failed")

    def test_published_resource_urls_resolve_local_and_external_assets(self):
        site = "https://personal-user.github.io/course-test1-pt/"
        local = AssetReference(
            source_file="week01/index.html",
            page_title="Week 1",
            asset_path="../images/diagram one.png?size=large#preview",
            asset_type="Image",
        )
        external = AssetReference(
            source_file="week01/index.html",
            page_title="Week 1",
            asset_path="https://cdn.example.com/image.png",
            asset_type="Image",
            external=True,
        )

        self.assertEqual(
            GitHubTranslationController._published_resource_url(site, local),
            "https://personal-user.github.io/course-test1-pt/images/diagram%20one.png?size=large#preview",
        )
        self.assertEqual(
            GitHubTranslationController._published_resource_url(site, external),
            external.asset_path,
        )
        self.assertEqual(
            GitHubTranslationController._published_page_url(
                site,
                "week01/lesson one.html",
            ),
            "https://personal-user.github.io/course-test1-pt/week01/lesson%20one.html",
        )

    def test_byui_logo_is_excluded_from_images_report_case_insensitively(self):
        logo = AssetReference(
            source_file="week01/index.html",
            page_title="Week 1",
            asset_path="../images/BYUI-logo.svg?cache=1",
            asset_type="Image",
        )
        course_image = AssetReference(
            source_file="week01/index.html",
            page_title="Week 1",
            asset_path="../images/diagram.svg",
            asset_type="Image",
        )

        self.assertTrue(GitHubTranslationController._exclude_asset_from_report(logo))
        self.assertFalse(GitHubTranslationController._exclude_asset_from_report(course_image))

    def test_supported_video_providers_use_video_package(self):
        controller = GitHubTranslationController.__new__(GitHubTranslationController)
        controller.scanner = GitHubRepositoryScanner()
        providers = (
            "https://www.youtube.com/watch?v=demo",
            "https://www.loom.com/embed/demo",
            "https://video.byui.brightspotcdn.com/demo",
            "https://cdnapisec.kaltura.com/p/demo",
        )

        for asset_path in providers:
            with self.subTest(asset_path=asset_path):
                asset = AssetReference(
                    source_file="week01/index.html",
                    page_title="Week 1",
                    asset_path=asset_path,
                    asset_type="Video",
                    external=True,
                )
                self.assertEqual(controller._asset_package(asset), "Video")

    def test_images_and_codepen_use_dedicated_packages(self):
        controller = GitHubTranslationController.__new__(GitHubTranslationController)
        controller.scanner = GitHubRepositoryScanner()
        image = AssetReference(
            source_file="week01/index.html",
            page_title="Week 1",
            asset_path="../images/diagram.png",
            asset_type="Image",
        )
        codepen = AssetReference(
            source_file="week01/index.html",
            page_title="Week 1",
            asset_path="https://codepen.io/example/pen/demo",
            asset_type="Codepen",
            external=True,
        )

        self.assertEqual(controller._asset_package(image), "Image")
        self.assertEqual(controller._asset_package(codepen), "Codepen")

    def test_public_links_use_canvas_github_and_external_packages(self):
        controller = GitHubTranslationController.__new__(GitHubTranslationController)
        controller.scanner = GitHubRepositoryScanner()
        cases = (
            ("https://school.instructure.com/courses/123", "Canvas"),
            ("https://github.com/byui-cse/course", "GitHub"),
            ("https://byui-cse.github.io/course/", "GitHub"),
            ("https://example.org/reference", "External"),
        )

        for asset_path, expected_package in cases:
            with self.subTest(asset_path=asset_path):
                asset = AssetReference(
                    source_file="week01/index.html",
                    page_title="Week 1",
                    asset_path=asset_path,
                    asset_type="Link",
                    external=True,
                )
                self.assertEqual(
                    controller._asset_package(asset),
                    expected_package,
                )

    def test_api_report_rows_redact_credentials_defensively(self):
        secret = "unstructured-secret-value"
        token = "ghp_1234567890abcdefghijklmnop"
        controller = GitHubTranslationController.__new__(GitHubTranslationController)

        rows = controller._api_setting_rows(
            [{
                "page_title": "Deployment",
                "source_file": "deploy.md",
                "provider": "GitHub",
                "setting": "API token",
                "value": secret,
                "context_summary": f"Use {token} for deployment.",
            }],
            "personal-user",
            "course-test1-pt",
        )

        serialized = repr(rows)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(token, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_report_rows_preserve_api_and_technical_setup_categories(self):
        controller = GitHubTranslationController.__new__(GitHubTranslationController)
        rows = controller._api_setting_rows(
            [
                {
                    "page_title": "API Setup",
                    "source_file": "setup.md",
                    "provider": "REST API",
                    "setting": "Endpoint",
                    "value": "GET /books",
                    "context_summary": "Endpoint para listar livros.",
                    "package": "API Setting",
                },
                {
                    "page_title": "Repository Setup",
                    "source_file": "setup.md",
                    "provider": "Git",
                    "setting": "Branch",
                    "value": "main",
                    "context_summary": "Branch usada no fluxo de trabalho.",
                    "package": "Technical Setup Instruction",
                },
            ],
            "personal-user",
            "course-test1-pt",
        )

        self.assertEqual(
            [row["package"] for row in rows],
            ["API Setting", "Technical Setup Instruction"],
        )
        self.assertTrue(rows[0]["asset_path"].startswith("API Setting —"))
        self.assertTrue(
            rows[1]["asset_path"].startswith("Technical Setup Instruction —")
        )
