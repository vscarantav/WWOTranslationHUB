import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.translation_id_registry import (  # noqa: E402
    TranslationIdRegistry,
    TranslationIdRegistryBuilder,
    TranslationIdRegistryError,
)


class TranslationIdRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp_dir.name)
        self._write_fixture()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, relative_path, content):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _write_fixture(self):
        self._write(
            "imsmanifest.xml",
            """<?xml version="1.0" encoding="utf-8"?>
<manifest identifier="manifest-1">
  <resources>
    <resource identifier="syllabus-resource" intendeduse="syllabus"
      type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
      href="course_settings/syllabus.html">
      <file href="course_settings/syllabus.html" />
    </resource>
    <resource identifier="page-attention" type="webcontent"
      href="wiki_content/attention-messaging-instructors-and-graders.html">
      <file href="wiki_content/attention-messaging-instructors-and-graders.html" />
    </resource>
    <resource identifier="page-setup" type="webcontent"
      href="wiki_content/setup-notes.html">
      <file href="wiki_content/setup-notes.html" />
    </resource>
    <resource identifier="assignment-w07"
      type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
      href="assignment-w07/w07-end-of-course-evaluation.html">
      <file href="assignment-w07/w07-end-of-course-evaluation.html" />
      <file href="assignment-w07/assignment_settings.xml" />
    </resource>
    <resource identifier="discussion-1"
      type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
      href="discussion-1/discussion.html">
      <file href="discussion-1/discussion.html" />
      <file href="discussion-1/assignment_settings.xml" />
    </resource>
    <resource identifier="quiz-1" type="imsqti_xmlv1p2/imscc_xmlv1p1/assessment">
      <file href="quiz-1/assessment_meta.xml" />
      <file href="quiz-1/assessment_qti.xml" />
    </resource>
    <resource identifier="quiz-1-meta"
      type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
      href="quiz-1/assessment_meta.xml">
      <file href="quiz-1/assessment_meta.xml" />
    </resource>
    <resource identifier="bank-1"
      type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
      href="non_cc_assessments/bank-1.xml.qti">
      <file href="non_cc_assessments/bank-1.xml.qti" />
    </resource>
    <resource identifier="file-1" type="webcontent"
      href="web_resources/guide.docx">
      <file href="web_resources/guide.docx" />
    </resource>
    <resource identifier="file-2" type="webcontent"
      href="web_resources/image.png">
      <file href="web_resources/image.png" />
    </resource>
  </resources>
</manifest>
""",
        )
        self._write(
            "course_settings/module_meta.xml",
            """<modules>
  <module identifier="module-1">
    <title>Week 01</title>
    <items>
      <item identifier="header-1"><content_type>ContextModuleSubHeader</content_type><title>Midweek</title></item>
      <item identifier="module-page"><content_type>WikiPage</content_type><title>Attention</title><identifierref>page-attention</identifierref></item>
      <item identifier="external-1"><content_type>ExternalUrl</content_type><title>Reference Site</title><url>https://example.test</url></item>
      <item identifier="tool-1"><content_type>ExternalTool</content_type><title>Practice Tool</title></item>
      <item identifier="module-w07"><content_type>Assignment</content_type><title>W07 End-of-Course Evaluation</title><identifierref>assignment-w07</identifierref></item>
      <item identifier="module-quiz"><content_type>Quizzes::Quiz</content_type><title>W01 Quiz</title><identifierref>quiz-1</identifierref></item>
    </items>
  </module>
</modules>""",
        )
        self._write(
            "course_settings/assignment_groups.xml",
            """<assignmentGroups><assignmentGroup identifier="group-1"><title>Week 01 Assignments</title></assignmentGroup></assignmentGroups>""",
        )
        self._write(
            "course_settings/grading_standards.xml",
            """<gradingStandards><gradingStandard identifier="standard-1"><title>Standard</title></gradingStandard></gradingStandards>""",
        )
        self._write(
            "course_settings/rubrics.xml",
            """<rubrics><rubric identifier="rubric-1"><title>Project Rubric</title></rubric></rubrics>""",
        )
        self._write("course_settings/context.xml", "<context><course_id>123</course_id></context>")
        self._write("course_settings/course_settings.xml", "<course><course_code>GS 170</course_code></course>")
        self._write(
            "course_settings/files_meta.xml",
            """<fileMeta><files><file identifier="file-1"><display_name>Study Guide.docx</display_name></file><file identifier="file-2"><display_name>Diagram.png</display_name></file></files></fileMeta>""",
        )
        self._write("course_settings/media_tracks.xml", "<mediaTracks />")
        self._write("course_settings/syllabus.html", "<html><body>Syllabus</body></html>")
        self._write(
            "wiki_content/attention-messaging-instructors-and-graders.html",
            "<html><head><title>Attention: Messaging Instructors and Graders</title></head><body>Attention</body></html>",
        )
        self._write(
            "wiki_content/setup-notes.html",
            "<html><head><title>Setup Notes</title></head><body>Setup</body></html>",
        )
        self._write(
            "assignment-w07/assignment_settings.xml",
            "<assignment identifier='assignment-w07'><title>W07 End-of-Course Evaluation</title></assignment>",
        )
        self._write(
            "assignment-w07/w07-end-of-course-evaluation.html",
            "<html><body>Evaluation</body></html>",
        )
        self._write(
            "discussion-1/assignment_settings.xml",
            "<assignment identifier='discussion-1'><title>W01 Discussion</title></assignment>",
        )
        self._write("discussion-1/discussion.html", "<html><body>Discuss</body></html>")
        self._write(
            "quiz-1/assessment_meta.xml",
            "<quiz identifier='quiz-1'><title>W01 Quiz</title></quiz>",
        )
        self._write("quiz-1/assessment_qti.xml", "<questestinterop />")
        self._write("non_cc_assessments/quiz-1.xml.qti", "<questestinterop />")
        self._write(
            "non_cc_assessments/bank-1.xml.qti",
            """<questestinterop><objectbank ident="bank-1"><qtimetadata><qtimetadatafield><fieldlabel>bank_title</fieldlabel><fieldentry>QB: GS 170 W01 Questions</fieldentry></qtimetadatafield></qtimetadata></objectbank></questestinterop>""",
        )
        self._write("web_resources/guide.docx", "not-a-real-docx")
        self._write("web_resources/image.png", "image")

    def _build(self, existing=None):
        return TranslationIdRegistryBuilder(
            self.root,
            "GS 170",
            source_course_id="123",
            existing_registry=existing,
        ).build()

    def test_builds_complete_logical_inventory_with_grouped_components(self):
        registry = self._build()
        by_key = {item["stable_key"]: item for item in registry.items}

        expected_keys = {
            "manifest:manifest-1",
            "manifest:page-attention",
            "manifest:page-setup",
            "manifest:assignment-w07",
            "manifest:discussion-1",
            "manifest:quiz-1",
            "manifest:bank-1",
            "manifest:file-1",
            "manifest:file-2",
            "module:module-1",
            "module-item:header-1",
            "module-item:external-1",
            "module-item:tool-1",
            "assignment-group:group-1",
            "grading-standard:standard-1",
            "rubric:rubric-1",
            "metadata:course-metadata",
            "metadata:course-settings",
            "metadata:file-metadata",
            "metadata:media-metadata",
        }
        self.assertTrue(expected_keys.issubset(by_key))
        self.assertEqual(by_key["manifest:assignment-w07"]["item_type"], "Assignment")
        self.assertEqual(by_key["manifest:discussion-1"]["item_type"], "Discussion")
        self.assertEqual(by_key["manifest:bank-1"]["item_type"], "Question Bank")
        self.assertEqual(by_key["manifest:file-1"]["source_title"], "Study Guide.docx")
        self.assertIn(
            "non_cc_assessments/quiz-1.xml.qti",
            by_key["manifest:quiz-1"]["package_paths"],
        )
        self.assertNotIn("manifest:quiz-1-meta", by_key)
        self.assertEqual(registry.course_code, "GS170")
        self.assertEqual(registry.source_course_id, "123")
        self.assertEqual(set(by_key["manifest:page-attention"]["instances"]), {"EN", "PTBR", "SPA", "FRA"})

    def test_inventory_and_allocation_are_deterministic(self):
        first = self._build().to_dict()
        first["items"].reverse()
        second = self._build().to_dict()
        self.assertEqual(
            sorted((item["stable_key"], item["translation_id"]) for item in first["items"]),
            sorted((item["stable_key"], item["translation_id"]) for item in second["items"]),
        )

    def test_reuses_ids_never_renumbers_and_never_reuses_retired_sequence(self):
        first = self._build()
        original = {
            item["stable_key"]: item["translation_id"] for item in first.items
        }
        setup_path = self.root / "wiki_content" / "setup-notes.html"
        setup_path.unlink()
        manifest_path = self.root / "imsmanifest.xml"
        manifest = manifest_path.read_text(encoding="utf-8")
        manifest = manifest.replace(
            "    <resource identifier=\"page-setup\" type=\"webcontent\"\n"
            "      href=\"wiki_content/setup-notes.html\">\n"
            "      <file href=\"wiki_content/setup-notes.html\" />\n"
            "    </resource>\n",
            "",
        ).replace(
            "  </resources>",
            "    <resource identifier=\"page-new\" type=\"webcontent\" href=\"wiki_content/new-page.html\"><file href=\"wiki_content/new-page.html\" /></resource>\n  </resources>",
        )
        manifest_path.write_text(manifest, encoding="utf-8")
        self._write(
            "wiki_content/new-page.html",
            "<html><head><title>New Page</title></head><body>New</body></html>",
        )

        second = self._build(existing=first)
        current = {item["stable_key"]: item for item in second.items}
        for stable_key, translation_id in original.items():
            self.assertEqual(current[stable_key]["translation_id"], translation_id)
        self.assertTrue(current["manifest:page-setup"]["retired"])
        old_sequence = int(original["manifest:page-setup"].rsplit("-", 1)[1])
        new_sequence = int(current["manifest:page-new"]["translation_id"].rsplit("-", 1)[1])
        self.assertGreater(new_sequence, old_sequence)

    def test_reuses_correct_existing_marker(self):
        page = self.root / "wiki_content" / "attention-messaging-instructors-and-graders.html"
        page.write_text(
            "<html><body>Attention<p>TranslationID: GS170-PG-027</p></body></html>",
            encoding="utf-8",
        )
        registry = self._build()
        item = next(
            item for item in registry.items if item["stable_key"] == "manifest:page-attention"
        )
        self.assertEqual(item["translation_id"], "GS170-PG-027")

    def test_blocks_conflicting_markers_and_duplicate_ids(self):
        page = self.root / "wiki_content" / "attention-messaging-instructors-and-graders.html"
        page.write_text(
            "<html><body><p>TranslationID: GS170-PG-001</p><p>TranslationID: GS170-PG-002</p></body></html>",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(TranslationIdRegistryError, "conflicting Translation IDs"):
            self._build()

        registry = self._build_after_removing_markers(page)
        duplicate = registry.to_dict()
        duplicate["items"][1]["translation_id"] = duplicate["items"][0]["translation_id"]
        duplicate["items"][1]["short_id"] = duplicate["items"][0]["short_id"]
        duplicate["items"][1]["item_type"] = duplicate["items"][0]["item_type"]
        with self.assertRaisesRegex(TranslationIdRegistryError, "Duplicate Translation ID"):
            TranslationIdRegistry.from_dict(duplicate)

    def _build_after_removing_markers(self, page):
        page.write_text("<html><body>Attention</body></html>", encoding="utf-8")
        return self._build()

    def test_atomic_round_trip_and_language_update_preserve_other_languages(self):
        registry = self._build()
        target = self.root / "registry" / "translation_ids.json"
        saved = registry.save(target)
        self.assertEqual(saved, str(target.resolve()))
        loaded = TranslationIdRegistry.load(target)
        translation_id = loaded.items[0]["translation_id"]
        before_ptbr = dict(loaded.items[0]["instances"]["PTBR"])
        loaded.update_instance(
            translation_id,
            "SPA",
            course_id="456",
            title="Título",
            presence="present",
            id_status="verified",
        )
        self.assertEqual(loaded.items[0]["instances"]["PTBR"], before_ptbr)
        self.assertEqual(loaded.items[0]["instances"]["SPA"]["course_id"], "456")
        self.assertFalse(any(target.parent.glob("*.tmp")))
        json.loads(target.read_text(encoding="utf-8"))

    def test_rejects_registry_for_another_course(self):
        existing = self._build().to_dict()
        existing["course_code"] = "OTHER101"
        for item in existing["items"]:
            old = item["translation_id"]
            item["translation_id"] = old.replace("GS170-", "OTHER101-", 1)
        with self.assertRaisesRegex(TranslationIdRegistryError, "belongs to course"):
            self._build(existing=existing)


if __name__ == "__main__":
    unittest.main()

