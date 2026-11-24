import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.canvas_translation_id_reconciler import (  # noqa: E402
    APPROVAL_PHRASE,
    CanvasTranslationIdError,
    CanvasTranslationIdReconciler,
    append_visible_marker,
    format_canvas_filename,
    trusted_canvas_domain_aliases,
)
from core.translation_id_registry import (  # noqa: E402
    LANGUAGES,
    TranslationIdRegistry,
    empty_language_instance,
)


def registry_item(translation_id, item_type, title, stable_key, **extra):
    item = {
        "translation_id": translation_id,
        "short_id": translation_id.split("-", 1)[1],
        "item_type": item_type,
        "source_title": title,
        "stable_key": stable_key,
        "package_paths": [],
        "placement": "registry_only",
        "retired": False,
        "instances": {language: empty_language_instance(language) for language in LANGUAGES},
    }
    item["instances"]["EN"]["title"] = title
    item.update(extra)
    return item


class FakeResponse:
    def __init__(self, payload, status_code=200, links=None):
        self.payload = payload
        self.status_code = status_code
        self.links = links or {}

    def json(self):
        return self.payload


class CanvasTranslationIdReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.rollback_root = Path.cwd() / "tests" / f"_translation_id_rollback_{uuid.uuid4().hex}"
        self.registry = TranslationIdRegistry(
            "GS170",
            "123",
            [
                registry_item(
                    "GS170-PG-001",
                    "Page",
                    "Teaching Notes",
                    "manifest:page-1",
                    package_paths=["wiki_content/teaching-notes.html"],
                    placement="html_body_end",
                ),
                registry_item(
                    "GS170-FI-001",
                    "File",
                    "Study Guide.docx",
                    "manifest:file-1",
                    placement="canvas_display_filename",
                ),
                registry_item(
                    "GS170-MO-001",
                    "Module Header",
                    "Midweek",
                    "module-item:header-1",
                    placement="module_meta_audit",
                ),
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.rollback_root, ignore_errors=True)

    def reconciler(self, request_func=None, mode="source-register", language="EN"):
        return CanvasTranslationIdReconciler(
            self.registry,
            "https://canvas.test/courses/123" if mode == "source-register" else "https://canvas.test/courses/456",
            language,
            mode,
            token="secret-token",
            api_url="https://canvas.test",
            request_func=request_func,
            rollback_root=self.rollback_root,
        )

    def test_selected_instructure_alias_is_authoritative_api_origin(self):
        reconciler = CanvasTranslationIdReconciler(
            self.registry,
            "https://byui.instructure.com/courses/123",
            "EN",
            "source-register",
            token="secret-token",
            api_url="https://byupw.instructure.com",
            rollback_root=self.rollback_root,
        )

        self.assertTrue(
            trusted_canvas_domain_aliases(
                "byupw.instructure.com",
                "byui.instructure.com",
            )
        )
        self.assertEqual(reconciler.api_origin, "https://byui.instructure.com")

    def test_unrelated_configured_domain_mismatch_is_rejected(self):
        with self.assertRaisesRegex(
            CanvasTranslationIdError,
            "not trusted Instructure aliases",
        ):
            CanvasTranslationIdReconciler(
                self.registry,
                "https://canvas.other.edu/courses/123",
                "EN",
                "source-register",
                token="secret-token",
                api_url="https://byupw.instructure.com",
                rollback_root=self.rollback_root,
            )

    def inventory(self, page_body="<p>Notes</p>", filename="Study Guide.docx"):
        return {
            "Course": [{"id": 123, "name": "GS 170", "syllabus_body": ""}],
            "Page": [{
                "page_id": 11,
                "url": "teaching-notes",
                "title": "Teaching Notes",
                "body": page_body,
                "html_url": "https://canvas.test/courses/123/pages/teaching-notes",
            }],
            "Assignment": [],
            "Quiz": [],
            "Discussion": [],
            "Announcement": [],
            "File": [{
                "id": 22,
                "display_name": filename,
                "filename": filename,
                "folder_id": 9,
                "url": "https://canvas.test/files/22/download",
            }],
            "Module": [{
                "id": 3,
                "items": [{"id": 33, "title": "Teaching Notes", "type": "Page"}],
            }],
        }

    def test_dry_run_classifies_missing_without_writes(self):
        reconciler = self.reconciler()
        plan = reconciler.plan(self.inventory())
        changes = {change["translation_id"]: change for change in plan["changes"]}

        self.assertEqual(changes["GS170-PG-001"]["status"], "Missing")
        self.assertEqual(
            changes["GS170-PG-001"]["proposed_value"],
            "<p>Notes</p><p>TranslationID: GS170-PG-001</p>",
        )
        self.assertEqual(changes["GS170-FI-001"]["status"], "Missing")
        self.assertEqual(
            changes["GS170-FI-001"]["proposed_value"],
            "Study Guide [GS170-FI-001].docx",
        )
        self.assertEqual(changes["GS170-MO-001"]["status"], "Not API Managed")
        self.assertEqual(plan["summary"], {"Missing": 2, "Not API Managed": 1})

    def test_dry_run_is_idempotent_and_detects_conflicts(self):
        correct = self.inventory(
            page_body="<p>Notes</p><p>TranslationID: GS170-PG-001</p>",
            filename="Study Guide [GS170-FI-001].docx",
        )
        plan = self.reconciler().plan(correct)
        statuses = {change["translation_id"]: change["status"] for change in plan["changes"]}
        self.assertEqual(statuses["GS170-PG-001"], "Correct")
        self.assertEqual(statuses["GS170-FI-001"], "Correct")

        conflict = self.inventory(page_body="TranslationID: GS170-PG-999")
        plan = self.reconciler().plan(conflict)
        page = next(change for change in plan["changes"] if change["item_type"] == "Page")
        self.assertEqual(page["status"], "Conflict")

    def test_title_matching_treats_export_underscore_as_canvas_colon(self):
        self.assertEqual(
            CanvasTranslationIdReconciler._normalize_title(
                "W01 Quiz_ Syllabus Clock.PNG"
            ),
            CanvasTranslationIdReconciler._normalize_title(
                "W01 Quiz: Syllabus Clock.PNG"
            ),
        )

    def test_assignment_discussions_are_added_to_discussion_inventory(self):
        responses = {
            "/api/v1/courses/123": {"id": 123},
            "/api/v1/courses/123/permissions": {
                "manage_wiki_update": True,
                "manage_files_edit": True,
            },
            "/api/v1/courses/123/pages": [],
            "/api/v1/courses/123/assignments": [{
                "id": 50,
                "name": "W01 Share",
                "discussion_topic": {
                    "id": 70,
                    "title": "W01 Share",
                    "message": "Discuss",
                },
            }],
            "/api/v1/courses/123/quizzes": [],
            "/api/v1/courses/123/discussion_topics": [],
            "/api/v1/courses/123/files": [],
            "/api/v1/courses/123/modules": [],
        }

        def request(method, url, **kwargs):
            path = url.split("canvas.test", 1)[1]
            return FakeResponse(responses[path])

        inventory = self.reconciler(request_func=request).discover()

        self.assertEqual(len(inventory["Discussion"]), 1)
        self.assertEqual(inventory["Discussion"][0]["id"], 70)
        self.assertEqual(inventory["Discussion"][0]["assignment_id"], 50)

    def test_file_collision_blocks_rename(self):
        inventory = self.inventory()
        inventory["File"].append({
            "id": 23,
            "display_name": "Study Guide [GS170-FI-001].docx",
            "folder_id": 9,
        })
        plan = self.reconciler().plan(inventory)
        file_change = next(change for change in plan["changes"] if change["item_type"] == "File")
        self.assertEqual(file_change["status"], "Conflict")
        self.assertIn("collide", file_change["detail"])

    def test_apply_requires_exact_approval_and_verifies_each_write(self):
        live_page = self.inventory()["Page"][0]
        live_file = self.inventory()["File"][0]

        def request(method, url, **kwargs):
            if method == "PUT" and "/pages/" in url:
                live_page["body"] = kwargs["data"]["wiki_page[body]"]
                return FakeResponse(dict(live_page))
            if method == "GET" and "/pages/" in url:
                return FakeResponse(dict(live_page))
            if method == "PUT" and "/files/" in url:
                live_file["display_name"] = kwargs["data"]["name"]
                live_file["filename"] = kwargs["data"]["name"]
                return FakeResponse(dict(live_file))
            if method == "GET" and "/files/" in url:
                return FakeResponse(dict(live_file))
            raise AssertionError((method, url, kwargs))

        reconciler = self.reconciler(request_func=request)
        plan = reconciler.plan(self.inventory())
        with self.assertRaisesRegex(CanvasTranslationIdError, "exact approval phrase"):
            reconciler.apply(plan, "yes")

        result = reconciler.apply(plan, APPROVAL_PHRASE)
        self.assertTrue(Path(result["rollback_directory"]).is_dir())
        self.assertEqual(live_page["body"].count("TranslationID:"), 1)
        self.assertEqual(live_file["display_name"], "Study Guide [GS170-FI-001].docx")
        self.assertTrue((Path(result["rollback_directory"]) / "registry-before.json").is_file())
        self.assertTrue((Path(result["rollback_directory"]) / "final-results.json").is_file())
        self.assertEqual(
            self.registry.items[0]["instances"]["EN"]["id_status"],
            "verified",
        )

    def test_apply_stops_on_failed_read_after_write(self):
        def request(method, url, **kwargs):
            if method == "PUT":
                return FakeResponse({})
            if "/pages/" in url:
                return FakeResponse(self.inventory()["Page"][0])
            if "/files/" in url:
                return FakeResponse(self.inventory()["File"][0])
            raise AssertionError((method, url))

        reconciler = self.reconciler(request_func=request)
        plan = reconciler.plan(self.inventory())
        with self.assertRaisesRegex(CanvasTranslationIdError, "write run stopped"):
            reconciler.apply(plan, APPROVAL_PHRASE)

    def test_target_mode_only_updates_selected_language_instance(self):
        reconciler = self.reconciler(mode="target-reconcile", language="PTBR")
        inventory = self.inventory()
        inventory["Page"][0]["title"] = "Notas de Ensino"
        self.registry.items[0]["instances"]["PTBR"]["title"] = "Notas de Ensino"
        plan = reconciler.plan(inventory)
        self.assertEqual(plan["language"], "PTBR")
        self.assertEqual(self.registry.items[0]["instances"]["EN"]["course_id"], None)
        self.assertEqual(self.registry.items[0]["instances"]["PTBR"]["course_id"], "456")
        self.assertEqual(self.registry.items[0]["instances"]["FRA"]["course_id"], None)

    def test_filename_and_content_helpers_are_idempotent_and_fail_closed(self):
        self.assertEqual(
            format_canvas_filename("Guide.final.docx", "GS170-FI-001"),
            "Guide.final [GS170-FI-001].docx",
        )
        self.assertEqual(
            format_canvas_filename("Guide [GS170-FI-001].docx", "GS170-FI-001"),
            "Guide [GS170-FI-001].docx",
        )
        with self.assertRaises(CanvasTranslationIdError):
            format_canvas_filename("Guide [GS170-FI-002].docx", "GS170-FI-001")
        self.assertEqual(
            format_canvas_filename(
                "Guide [GS170-FI-002].docx",
                "GS170-FI-001",
                retired_ids=["GS170-FI-002"],
            ),
            "Guide [GS170-FI-001].docx",
        )
        self.assertEqual(
            append_visible_marker("<body>Text</body>", "GS170-PG-001"),
            "<body>Text<p>TranslationID: GS170-PG-001</p></body>",
        )
        self.assertEqual(
            append_visible_marker(
                "<body>Text<p>TranslationID: GS170-PG-002</p></body>",
                "GS170-PG-001",
                retired_ids=["GS170-PG-002"],
            ),
            "<body>Text<p>TranslationID: GS170-PG-001</p></body>",
        )
        self.assertEqual(
            append_visible_marker(
                '<p>Overview</p><script src="mobile.js"></script>',
                "GS170-AS-001",
            ),
            '<p>Overview</p><p>TranslationID: GS170-AS-001</p><script src="mobile.js"></script>',
        )
        self.assertEqual(
            append_visible_marker(
                '<body><p>Overview</p><script src="mobile.js"></script></body>',
                "GS170-PG-001",
            ),
            '<body><p>Overview</p><p>TranslationID: GS170-PG-001</p><script src="mobile.js"></script></body>',
        )

    def test_apply_verifies_when_canvas_reorders_trailing_script(self):
        live_page = self.inventory()["Page"][0]
        live_page["body"] = '<p>Overview</p><script src="mobile.js"></script>'
        live_file = self.inventory()["File"][0]

        def request(method, url, **kwargs):
            if method == "PUT" and "/pages/" in url:
                # Simulate Canvas sanitizer placing script after the added paragraph
                live_page["body"] = (
                    '<p>Overview</p><p>TranslationID: GS170-PG-001</p><script src="mobile.js"></script>'
                )
                return FakeResponse(dict(live_page))
            if method == "GET" and "/pages/" in url:
                return FakeResponse(dict(live_page))
            if method == "PUT" and "/files/" in url:
                live_file["display_name"] = kwargs["data"]["name"]
                live_file["filename"] = kwargs["data"]["name"]
                return FakeResponse(dict(live_file))
            if method == "GET" and "/files/" in url:
                return FakeResponse(dict(live_file))
            raise AssertionError((method, url, kwargs))

        reconciler = self.reconciler(request_func=request)
        plan = reconciler.plan(self.inventory(page_body='<p>Overview</p><script src="mobile.js"></script>'))
        result = reconciler.apply(plan, APPROVAL_PHRASE)
        self.assertIn("rollback_directory", result)
        self.assertEqual(
            self.registry.items[0]["instances"]["EN"]["id_status"],
            "verified",
        )

    def test_plan_and_apply_replaces_retired_ids_without_conflict(self):
        retired_item = {
            "item_type": "File",
            "source_title": "Old Guide.docx",
            "stable_key": "path:old-guide.docx",
            "package_paths": ["old-guide.docx"],
            "placement": "canvas_display_filename",
            "translation_id": "GS170-FI-099",
            "short_id": "FI-099",
            "retired": True,
            "instances": {
                "EN": {"course_id": "123", "content_id": None, "presence": "missing", "id_status": "not_checked"},
                "PTBR": {"course_id": None, "content_id": None, "presence": "not_translated", "id_status": "not_checked"},
                "SPA": {"course_id": None, "content_id": None, "presence": "not_translated", "id_status": "not_checked"},
                "FRA": {"course_id": None, "content_id": None, "presence": "not_translated", "id_status": "not_checked"},
            },
        }
        self.registry.items.append(retired_item)
        inventory = self.inventory()
        inventory["File"][0]["display_name"] = "Study Guide [GS170-FI-099].docx"
        inventory["File"][0]["filename"] = "Study Guide [GS170-FI-099].docx"

        live_file = inventory["File"][0]
        live_page = inventory["Page"][0]

        def request(method, url, **kwargs):
            if method == "PUT" and "/files/" in url:
                live_file["display_name"] = kwargs["data"]["name"]
                live_file["filename"] = kwargs["data"]["name"]
                return FakeResponse(dict(live_file))
            if method == "GET" and "/files/" in url:
                return FakeResponse(dict(live_file))
            if method == "PUT" and "/pages/" in url:
                live_page["body"] = kwargs["data"]["wiki_page[body]"]
                return FakeResponse(dict(live_page))
            if method == "GET" and "/pages/" in url:
                return FakeResponse(dict(live_page))
            raise AssertionError((method, url, kwargs))

        reconciler = self.reconciler(request_func=request)
        plan = reconciler.plan(inventory)
        file_change = next(change for change in plan["changes"] if change["translation_id"] == "GS170-FI-001")
        self.assertEqual(file_change["status"], "Missing")
        self.assertEqual(file_change["proposed_value"], "Study Guide [GS170-FI-001].docx")

        retired_change = next(change for change in plan["changes"] if change["translation_id"] == "GS170-FI-099")
        self.assertEqual(retired_change["status"], "Retired")

        result = reconciler.apply(plan, APPROVAL_PHRASE)
        self.assertIn("rollback_directory", result)
        self.assertEqual(live_file["display_name"], "Study Guide [GS170-FI-001].docx")

    def test_domain_and_source_course_mismatches_block_initialization(self):
        with self.assertRaisesRegex(CanvasTranslationIdError, "domain"):
            CanvasTranslationIdReconciler(
                self.registry,
                "https://other.test/courses/123",
                "EN",
                "source-register",
                token="token",
                api_url="https://canvas.test",
            )
        with self.assertRaisesRegex(CanvasTranslationIdError, "source course ID"):
            CanvasTranslationIdReconciler(
                self.registry,
                "https://canvas.test/courses/999",
                "EN",
                "source-register",
                token="token",
                api_url="https://canvas.test",
            )


if __name__ == "__main__":
    unittest.main()

