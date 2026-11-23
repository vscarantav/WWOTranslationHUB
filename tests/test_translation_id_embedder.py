import io
import shutil
import sys
import unittest
import uuid
import zipfile
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.translation_id_embedder import (  # noqa: E402
    TranslationIdEmbedder,
    TranslationIdEmbeddingError,
)
from core.translation_id_registry import (  # noqa: E402
    LANGUAGES,
    TranslationIdRegistry,
    empty_language_instance,
)


def item(translation_id, item_type, stable_key, paths, placement):
    instances = {language: empty_language_instance(language) for language in LANGUAGES}
    instances["EN"]["title"] = stable_key
    return {
        "translation_id": translation_id,
        "short_id": translation_id.split("-", 1)[1],
        "item_type": item_type,
        "source_title": stable_key,
        "stable_key": stable_key,
        "package_paths": paths,
        "placement": placement,
        "retired": False,
        "instances": instances,
    }


class TranslationIdEmbedderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_translation_id_embed_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self._write("wiki_content/page.html", "<html><body><p>Page</p></body></html>")
        self._write("assignment-1/assignment.html", "<html><body>Assignment</body></html>")
        self._write(
            "quiz-1/assessment_meta.xml",
            "<quiz><title>Quiz</title><description>&lt;p&gt;Quiz description&lt;/p&gt;</description></quiz>",
        )
        self._write(
            "discussion-1/topic_meta.xml",
            "<discussion_topic><title>Discussion</title><message>&lt;p&gt;Discuss&lt;/p&gt;</message></discussion_topic>",
        )
        self._write(
            "non_cc_assessments/bank.qti",
            "<questestinterop><objectbank ident='bank'><qtimetadata><qtimetadatafield><fieldlabel>bank_title</fieldlabel><fieldentry>QB: GS 170 Questions</fieldentry></qtimetadatafield></qtimetadata></objectbank></questestinterop>",
        )
        self._write_docx("web_resources/guide.docx")
        self._write("web_resources/image.png", "unchanged image bytes")
        self.registry = TranslationIdRegistry(
            "GS170",
            "123",
            [
                item("GS170-PG-001", "Page", "page", ["wiki_content/page.html"], "html_body_end"),
                item("GS170-AS-001", "Assignment", "assignment", ["assignment-1/assignment.html"], "assignment_html_body_end"),
                item("GS170-QZ-001", "Quiz", "quiz", ["quiz-1/assessment_meta.xml"], "quiz_description"),
                item("GS170-DI-001", "Discussion", "discussion", ["discussion-1/topic_meta.xml"], "discussion_visible_text_end"),
                item("GS170-QB-001", "Question Bank", "bank", ["non_cc_assessments/bank.qti"], "question_bank_title"),
                item("GS170-FI-001", "File", "guide", ["web_resources/guide.docx"], "docx_document_end_and_canvas_display_filename"),
                item("GS170-FI-002", "File", "image", ["web_resources/image.png"], "canvas_display_filename"),
                item("GS170-MO-001", "Module Header", "header", ["course_settings/module_meta.xml"], "module_meta_audit"),
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_docx(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Guide</w:t></w:r></w:p><w:sectPr/></w:body></w:document>',
            )
            archive.writestr("word/styles.xml", b"UNCHANGED-STYLES")
            archive.comment = b"preserve-comment"

    def test_embeds_every_supported_target_and_skips_registry_only_content(self):
        original_image = (self.root / "web_resources/image.png").read_bytes()
        result = TranslationIdEmbedder(self.root, self.registry).embed_all()

        self.assertEqual(result["embedded"], 6)
        self.assertEqual(result["skipped"], 2)
        self.assertIn(
            "<p>TranslationID: GS170-PG-001</p></body>",
            (self.root / "wiki_content/page.html").read_text(encoding="utf-8"),
        )
        quiz = (self.root / "quiz-1/assessment_meta.xml").read_text(encoding="utf-8")
        self.assertIn("&lt;p&gt;TranslationID: GS170-QZ-001&lt;/p&gt;", quiz)
        discussion = (self.root / "discussion-1/topic_meta.xml").read_text(encoding="utf-8")
        self.assertIn("&lt;p&gt;TranslationID: GS170-DI-001&lt;/p&gt;", discussion)
        bank = (self.root / "non_cc_assessments/bank.qti").read_text(encoding="utf-8")
        self.assertIn("QB: GS 170 Questions TranslationID: GS170-QB-001", bank)
        with zipfile.ZipFile(self.root / "web_resources/guide.docx") as archive:
            document = archive.read("word/document.xml").decode("utf-8")
            self.assertLess(document.index("TranslationID:"), document.index("<w:sectPr"))
            self.assertEqual(archive.read("word/styles.xml"), b"UNCHANGED-STYLES")
            self.assertEqual(archive.comment, b"preserve-comment")
        self.assertEqual((self.root / "web_resources/image.png").read_bytes(), original_image)

    def test_second_run_is_idempotent(self):
        embedder = TranslationIdEmbedder(self.root, self.registry)
        embedder.embed_all()
        result = embedder.embed_all()
        self.assertEqual(result["already_present"], 6)
        page = (self.root / "wiki_content/page.html").read_text(encoding="utf-8")
        self.assertEqual(page.count("TranslationID:"), 1)
        with zipfile.ZipFile(self.root / "web_resources/guide.docx") as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        self.assertEqual(document.count("TranslationID:"), 1)

    def test_conflicting_marker_blocks_without_overwrite(self):
        path = self.root / "wiki_content/page.html"
        original = "<html><body>TranslationID: GS170-PG-999</body></html>"
        path.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(TranslationIdEmbeddingError, "Different Translation ID"):
            TranslationIdEmbedder(self.root, self.registry).embed_all()
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_required_target_blocks(self):
        (self.root / "quiz-1/assessment_meta.xml").unlink()
        with self.assertRaisesRegex(TranslationIdEmbeddingError, "No registered package target"):
            TranslationIdEmbedder(self.root, self.registry).embed_all()

    def test_validation_detects_removed_marker(self):
        embedder = TranslationIdEmbedder(self.root, self.registry)
        embedder.embed_all()
        (self.root / "assignment-1/assignment.html").write_text(
            "<html><body>Assignment</body></html>", encoding="utf-8"
        )
        with self.assertRaisesRegex(TranslationIdEmbeddingError, "validation found markers none"):
            embedder.validate_all()


if __name__ == "__main__":
    unittest.main()

