import tempfile
import unittest
from pathlib import Path

from lxml import etree

from app.core.canvas_assignment_template import (
    CanvasAssignmentTemplateClient,
    W07AssignmentTemplateInstaller,
    is_w07_end_of_course_evaluation,
)


ASSIGNMENT_NAMESPACE = "http://canvas.instructure.com/xsd/cccv1p0"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def portuguese_assignment():
    return {
        "id": 816997,
        "name": "S07 Avaliação de Fim de Curso",
        "description": "<p>Descrição aprovada em português.</p>",
        "due_at": None,
        "lock_at": None,
        "unlock_at": None,
        "points_possible": 0.0,
        "grading_type": "points",
        "submission_types": ["external_tool"],
        "external_tool_tag_attributes": {
            "url": "https://example.test/approved-portuguese-survey",
            "new_tab": True,
            "external_data": "",
            "content_id": 145,
        },
        "workflow_state": "published",
        "published": True,
        "omit_from_final_grade": False,
        "hide_in_gradebook": False,
        "only_visible_to_overrides": False,
        "post_to_sis": False,
        "peer_reviews": False,
        "automatic_peer_reviews": False,
        "anonymous_peer_reviews": False,
        "grade_group_students_individually": False,
        "intra_group_peer_reviews": False,
        "moderated_grading": False,
        "grader_count": 0,
        "grader_comments_visible_to_graders": True,
        "anonymous_grading": False,
        "graders_anonymous_to_graders": False,
        "grader_names_visible_to_final_grader": True,
        "anonymous_instructor_annotations": False,
        "require_lockdown_browser": False,
        "post_manually": False,
        "position": 1,
    }


class W07TitleMatchingTests(unittest.TestCase):
    def test_matches_punctuation_and_wording_variants(self):
        variants = (
            "W07 End-of-Course Evaluation",
            "W07: End of Course Evaluation",
            "Week 7 Course Evaluation",
            "w07_end_of_course_survey",
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertTrue(is_w07_end_of_course_evaluation(variant))

    def test_rejects_unrelated_evaluations(self):
        self.assertFalse(
            is_w07_end_of_course_evaluation(
                "Course Considerations for Instructor Evaluation"
            )
        )


class CanvasAssignmentTemplateClientTests(unittest.TestCase):
    def test_fetches_exact_template_assignment_with_bearer_token(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(portuguese_assignment())

        client = CanvasAssignmentTemplateClient(
            token="secret-token",
            request_get=fake_get,
        )

        result = client.fetch()

        self.assertEqual(result["id"], 816997)
        self.assertEqual(
            calls[0][0],
            "https://byupw.instructure.com/api/v1/courses/11564/assignments/816997",
        )
        self.assertEqual(
            calls[0][1]["headers"],
            {"Authorization": "Bearer secret-token"},
        )
        self.assertEqual(calls[0][1]["timeout"], 30)


class W07AssignmentTemplateInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        )
        self.course_root = Path(self.temp_dir.name)
        self.assignment_dir = self.course_root / "gassignment"
        self.assignment_dir.mkdir()
        (self.course_root / "course_settings").mkdir()

        (self.assignment_dir / "assignment_settings.xml").write_text(
            f'''<?xml version="1.0" encoding="UTF-8"?>
<assignment identifier="gassignment" xmlns="{ASSIGNMENT_NAMESPACE}">
  <title>W07: End of Course Evaluation</title>
  <due_at>2026-10-17T23:59:59Z</due_at>
  <lock_at>2026-10-17T23:59:59Z</lock_at>
  <unlock_at>2026-10-03T00:00:00Z</unlock_at>
  <all_day_date>2026-10-17</all_day_date>
  <assignment_group_identifierref>gcourse-specific-group</assignment_group_identifierref>
  <workflow_state>published</workflow_state>
  <assignment_overrides><assignment_override identifier="old"/></assignment_overrides>
  <allowed_extensions/>
  <has_group_category>false</has_group_category>
  <points_possible>1.0</points_possible>
  <grading_type>points</grading_type>
  <all_day>true</all_day>
  <submission_types>external_tool</submission_types>
  <position>7</position>
  <peer_review_count>0</peer_review_count>
  <peer_reviews>false</peer_reviews>
  <automatic_peer_reviews>false</automatic_peer_reviews>
  <anonymous_peer_reviews>false</anonymous_peer_reviews>
  <grade_group_students_individually>false</grade_group_students_individually>
  <omit_from_final_grade>true</omit_from_final_grade>
  <hide_in_gradebook>false</hide_in_gradebook>
  <intra_group_peer_reviews>false</intra_group_peer_reviews>
  <only_visible_to_overrides>false</only_visible_to_overrides>
  <post_to_sis>false</post_to_sis>
  <moderated_grading>false</moderated_grading>
  <grader_count>0</grader_count>
  <grader_comments_visible_to_graders>true</grader_comments_visible_to_graders>
  <anonymous_grading>false</anonymous_grading>
  <graders_anonymous_to_graders>false</graders_anonymous_to_graders>
  <grader_names_visible_to_final_grader>true</grader_names_visible_to_final_grader>
  <anonymous_instructor_annotations>false</anonymous_instructor_annotations>
  <external_tool_external_identifier>old</external_tool_external_identifier>
  <external_tool_url>https://example.test/english</external_tool_url>
  <external_tool_data_json>""</external_tool_data_json>
  <external_tool_link_settings_json>{{}}</external_tool_link_settings_json>
  <external_tool_new_tab>false</external_tool_new_tab>
  <lockdown_browser_settings>{{"require_lockdown_browser":false}}</lockdown_browser_settings>
  <post_policy><post_manually>false</post_manually></post_policy>
</assignment>
''',
            encoding="utf-8",
        )
        (self.assignment_dir / "w07-course-evaluation.html").write_text(
            "<html><head><title>English</title></head><body>English</body></html>",
            encoding="utf-8",
        )
        (self.course_root / "imsmanifest.xml").write_text(
            '''<?xml version="1.0"?>
<manifest><organizations><organization>
  <item identifier="module-item" identifierref="gassignment">
    <title>W07 End-of-Course Evaluation</title>
  </item>
</organization></organizations></manifest>
''',
            encoding="utf-8",
        )
        (self.course_root / "course_settings" / "module_meta.xml").write_text(
            '''<?xml version="1.0"?>
<modules><module><items><item>
  <content_type>Assignment</content_type>
  <title>W07 End-of-Course Evaluation</title>
  <identifierref>gassignment</identifierref>
  <new_tab>false</new_tab>
</item></items></module></modules>
''',
            encoding="utf-8",
        )

        client = CanvasAssignmentTemplateClient(
            token="token",
            request_get=lambda *_args, **_kwargs: FakeResponse(
                portuguese_assignment()
            ),
        )
        self.installer = W07AssignmentTemplateInstaller(client)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_replaces_english_assignment_from_canvas_payload(self):
        installation = self.installer.install(self.course_root)

        tree = etree.parse(str(installation.assignment_settings_path))
        root = tree.getroot()
        values = {
            etree.QName(child).localname: child.text for child in root
        }
        self.assertEqual(root.get("identifier"), "gassignment")
        self.assertEqual(
            values["assignment_group_identifierref"],
            "gcourse-specific-group",
        )
        self.assertEqual(values["title"], "S07 Avaliação de Fim de Curso")
        self.assertIsNone(values["due_at"])
        self.assertIsNone(values["lock_at"])
        self.assertIsNone(values["unlock_at"])
        self.assertEqual(values["points_possible"], "0.0")
        self.assertEqual(values["position"], "7")
        self.assertEqual(values["omit_from_final_grade"], "false")
        self.assertEqual(
            values["external_tool_url"],
            "https://example.test/approved-portuguese-survey",
        )
        self.assertEqual(values["external_tool_new_tab"], "true")
        overrides = next(
            child
            for child in root
            if etree.QName(child).localname == "assignment_overrides"
        )
        self.assertEqual(len(overrides), 0)

        description = installation.description_path.read_text(encoding="utf-8")
        self.assertIn("Assignment: S07 Avaliação de Fim de Curso", description)
        self.assertIn("Descrição aprovada em português.", description)
        self.assertNotIn(">English<", description)

    def test_enforces_template_title_and_launch_behavior_in_package_references(self):
        installation = self.installer.install(self.course_root)

        updated = self.installer.enforce_package_references(
            self.course_root,
            installation,
        )

        self.assertEqual(updated, 2)
        manifest = (self.course_root / "imsmanifest.xml").read_text(
            encoding="utf-8"
        )
        module_meta = (
            self.course_root / "course_settings" / "module_meta.xml"
        ).read_text(encoding="utf-8")
        self.assertIn("S07 Avaliação de Fim de Curso", manifest)
        self.assertIn("S07 Avaliação de Fim de Curso", module_meta)
        self.assertIn("<new_tab>true</new_tab>", module_meta)
        self.assertIn('identifierref="gassignment"', manifest)


if __name__ == "__main__":
    unittest.main()
