"""
Tests for the XML/QTI manual-review recovery flow.

Verifies:
  1. XML/QTI files that fail all retries land in manual_review_failures
     rather than raising an exception from translate_files().
  2. Other file types (e.g. .html) that fail all retries still raise.
  3. process_directory() completes (does not raise) when only XML/QTI
     files fail, so IMSCC packaging and the report can proceed.
  4. controller.manual_review_failures is empty when all files succeed.
"""
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from controller import TranslationController


def _make_bare_controller():
    """Return a TranslationController with all heavy dependencies stubbed out."""
    ctrl = object.__new__(TranslationController)
    ctrl.target_language = "PTBR"
    ctrl.link_prompt_callback = None
    ctrl.target_course_id = None
    ctrl._attention_package_prepared = False
    ctrl._attention_page_present = False
    ctrl._gemini_translation_pages = {}
    ctrl._gemini_translation_pages_lock = threading.Lock()
    ctrl._w07_template_installation = None
    ctrl._w07_template_paths = set()
    ctrl.manual_review_failures = []
    ctrl.log_lock = threading.Lock()
    ctrl._log = MagicMock()
    ctrl.app_dir = str(APP_DIR)
    ctrl.hub_dir = str(APP_DIR.parent)
    ctrl.filepaths = []
    ctrl.bots = {}
    ctrl.auditor = MagicMock()
    ctrl.scripture_checker = MagicMock()
    ctrl.workspace = MagicMock()
    ctrl.workspace.imscc_path = "fake.imscc"
    ctrl.workspace.output_dir = "/fake/output"
    ctrl.link_processor = MagicMock()
    ctrl.w07_template_installer = MagicMock()
    ctrl.instructions = {}
    ctrl.log_filepath = str(APP_DIR / "bots" / "translation_log.txt")
    return ctrl


class XmlQtiManualReviewFlowTests(unittest.TestCase):

    def test_xml_failure_lands_in_manual_review_failures_not_raised(self):
        """A QTI file that fails every attempt must not abort translate_files()."""
        ctrl = _make_bare_controller()
        ctrl.filepaths = ["/fake/dir/quiz.xml.qti"]

        def bad_process_file(path):
            raise RuntimeError("Unable to translate XML batch after 3 attempts.")

        ctrl.process_file = bad_process_file

        # Should NOT raise – XML/QTI failures are recoverable
        ctrl.translate_files()

        self.assertEqual(len(ctrl.manual_review_failures), 1)
        failed_path, failed_exc = ctrl.manual_review_failures[0]
        self.assertEqual(failed_path, "/fake/dir/quiz.xml.qti")
        self.assertIn("Unable to translate XML batch", str(failed_exc))

    def test_html_failure_still_raises(self):
        """A plain HTML file that fails every retry must still abort translate_files()."""
        ctrl = _make_bare_controller()
        ctrl.filepaths = ["/fake/dir/page.html"]

        def bad_process_file(path):
            raise RuntimeError("HTML translation failed unexpectedly.")

        ctrl.process_file = bad_process_file

        with self.assertRaises(RuntimeError):
            ctrl.translate_files()

        # manual_review_failures must stay empty for non-XML/QTI errors
        self.assertEqual(ctrl.manual_review_failures, [])

    def test_xml_and_html_failures_partial_abort(self):
        """Mixed failures: HTML raises immediately; XML/QTI accumulates."""
        ctrl = _make_bare_controller()
        ctrl.filepaths = ["/fake/dir/quiz.xml.qti", "/fake/dir/page.html"]

        def bad_process_file(path):
            raise RuntimeError(f"Translation failed: {path}")

        ctrl.process_file = bad_process_file

        # The HTML failure triggers a hard abort
        with self.assertRaises(RuntimeError):
            ctrl.translate_files()

    def test_no_failures_leaves_manual_review_empty(self):
        """When all files translate successfully, manual_review_failures stays empty."""
        ctrl = _make_bare_controller()
        ctrl.filepaths = ["/fake/dir/quiz.xml.qti", "/fake/dir/page.html"]
        ctrl.process_file = MagicMock()  # succeeds silently

        ctrl.translate_files()

        self.assertEqual(ctrl.manual_review_failures, [])

    def test_multiple_qti_failures_all_captured(self):
        """Every QTI failure in a batch is captured, not just the first one."""
        ctrl = _make_bare_controller()
        ctrl.filepaths = [
            "/fake/dir/qb1.xml.qti",
            "/fake/dir/qb2.xml.qti",
            "/fake/dir/qb3.xml.qti",
        ]

        def bad_process_file(path):
            raise RuntimeError("Unable to translate XML batch after 3 attempts.")

        ctrl.process_file = bad_process_file

        ctrl.translate_files()

        self.assertEqual(len(ctrl.manual_review_failures), 3)
        failed_paths = [fp for fp, _ in ctrl.manual_review_failures]
        self.assertIn("/fake/dir/qb1.xml.qti", failed_paths)
        self.assertIn("/fake/dir/qb2.xml.qti", failed_paths)
        self.assertIn("/fake/dir/qb3.xml.qti", failed_paths)

    def test_process_directory_completes_on_xml_failure(self):
        """process_directory() must not raise when only XML/QTI files fail."""
        ctrl = _make_bare_controller()

        # Stub out every step except translate_files
        ctrl._prepare_attention_messaging_package = MagicMock()
        ctrl._prepare_w07_template_assignment = MagicMock()
        ctrl.workspace.collect_files = MagicMock(return_value=["/fake/qb.xml.qti"])
        ctrl.link_processor.filepaths = []
        ctrl.link_processor.pre_process_links = MagicMock()
        ctrl._enforce_w07_template_references = MagicMock()
        ctrl.workspace.compress_to_imscc = MagicMock()

        def bad_process_file(path):
            raise RuntimeError("Unable to translate XML batch after 3 attempts.")

        ctrl.process_file = bad_process_file

        # Must complete without raising
        ctrl.process_directory()

        # IMSCC packaging still ran
        ctrl.workspace.compress_to_imscc.assert_called_once()
        # Failed file recorded
        self.assertEqual(len(ctrl.manual_review_failures), 1)


    def test_manual_review_failures_appear_in_gemini_translation_pages_as_failed(self):
        """Failed XML/QTI files must be reported in get_gemini_translation_pages() with status Failed."""
        ctrl = _make_bare_controller()
        ctrl._extract_title_from_filepath = MagicMock(return_value="Quiz Title")
        ctrl.manual_review_failures = [
            ("/fake/dir/quiz.xml.qti", RuntimeError("Unable to translate XML batch after 3 attempts."))
        ]

        pages = ctrl.get_gemini_translation_pages()

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["status"], "Failed")
        self.assertEqual(pages[0]["title"], "Quiz Title")
        self.assertIn("Manual review required", pages[0]["details"])
        self.assertIn("Unable to translate XML batch", pages[0]["details"])

    def test_gemini_translation_pages_merges_successes_and_failures(self):
        """Review pages list must include both successful pages and failed ones."""
        ctrl = _make_bare_controller()
        ctrl._extract_title_from_filepath = MagicMock(return_value="Extracted")
        ctrl._is_translation_review_candidate = MagicMock(return_value=True)
        good_path = str(Path("/fake/dir/good_page.html").resolve())
        ctrl._gemini_translation_pages = {
            good_path: {
                "title": "Good Page",
                "filepath": good_path,
            }
        }
        ctrl.manual_review_failures = [
            ("/fake/dir/failed_quiz.xml.qti", RuntimeError("Batch failure"))
        ]

        pages = ctrl.get_gemini_translation_pages()

        self.assertEqual(len(pages), 2)
        statuses = {p["filepath"]: p.get("status", "Translated") for p in pages}
        self.assertEqual(statuses.get(good_path), "Translated")
        self.assertEqual(statuses.get(str(Path("/fake/dir/failed_quiz.xml.qti").resolve())), "Failed")


if __name__ == "__main__":
    unittest.main()
