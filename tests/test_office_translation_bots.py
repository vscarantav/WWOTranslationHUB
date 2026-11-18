import io
import json
import shutil
import sys
import unittest
import uuid
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Font
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.docx_bot import DOCXTranslationBot
from bots.office_xml_bot import OfficeTranslationResult
from bots.xlsx_bot import XLSXTranslationBot
from controller import TranslationController


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class _FakeXMLAgent:
    def __init__(self):
        self.calls = []

    def translate_text_items(
        self,
        items,
        relevant_glossary=None,
        relevant_scriptures=None,
        context_label="",
        additional_constraints="",
    ):
        self.calls.append(
            (
                dict(items),
                relevant_glossary,
                relevant_scriptures,
                context_label,
                additional_constraints,
            )
        )
        prefix = "PT " if additional_constraints else "PT: "
        return {item_id: f"{prefix}{text}" for item_id, text in items.items()}


class _MappingXMLAgent(_FakeXMLAgent):
    def __init__(self, translations):
        super().__init__()
        self.translations = translations

    def translate_text_items(
        self,
        items,
        relevant_glossary=None,
        relevant_scriptures=None,
        context_label="",
        additional_constraints="",
    ):
        self.calls.append(
            (
                dict(items),
                relevant_glossary,
                relevant_scriptures,
                context_label,
                additional_constraints,
            )
        )
        return {
            item_id: self.translations.get(text, f"PT: {text}")
            for item_id, text in items.items()
        }


def _zip_bytes(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return output.getvalue()


def _replace_zip_member(package, member_name, replacement):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package), "r") as source, zipfile.ZipFile(
        output,
        "w",
    ) as target:
        for info in source.infolist():
            content = replacement if info.filename == member_name else source.read(info)
            target.writestr(info, content)
    return output.getvalue()


def _docx_fixture():
    return _zip_bytes({
        "[Content_Types].xml": (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        ),
        "_rels/.rels": b"<Relationships/>",
        "word/document.xml": (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            b'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            b'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
            b'mc:Ignorable="w14">'
            b'<w:body><w:p><w:r><w:rPr><w:b/></w:rPr>'
            b'<w:t xml:space="preserve"> Hello world </w:t></w:r>'
            b'<w:r><w:instrText>HYPERLINK "https://example.com"</w:instrText></w:r>'
            b'</w:p></w:body></w:document>'
        ),
        "word/header1.xml": (
            b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:p><w:r><w:t>Header text</w:t></w:r></w:p></w:hdr>'
        ),
        "word/styles.xml": (
            b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/>'
            b'</w:style></w:styles>'
        ),
        "word/media/image1.png": b"\x89PNG\r\nunchanged-image",
    })


class OfficeTranslationBotTests(unittest.TestCase):
    def test_docx_translates_document_and_header_without_changing_structure(self):
        source = _docx_fixture()
        xml_agent = _FakeXMLAgent()
        bot = DOCXTranslationBot(xml_agent)

        result = bot.translate_document(
            source,
            relevant_glossary={"Header": "Cabeçalho"},
            document_name="lesson.docx",
        )

        self.assertEqual(result.outcome, "Translated")
        self.assertEqual(result.translated_nodes, 2)
        self.assertEqual(result.translated_parts, 2)
        self.assertEqual(len(xml_agent.calls), 1)
        with zipfile.ZipFile(io.BytesIO(source)) as original_archive, zipfile.ZipFile(
            io.BytesIO(result.content)
        ) as translated_archive:
            self.assertEqual(
                translated_archive.namelist(),
                original_archive.namelist(),
            )
            self.assertEqual(
                translated_archive.read("word/media/image1.png"),
                original_archive.read("word/media/image1.png"),
            )
            self.assertEqual(
                translated_archive.read("word/styles.xml"),
                original_archive.read("word/styles.xml"),
            )
            translated_document_xml = translated_archive.read("word/document.xml")
            self.assertIn(b'xmlns:w14=', translated_document_xml)
            self.assertIn(b'mc:Ignorable="w14"', translated_document_xml)
            document_root = ET.fromstring(translated_document_xml)
            text_node = document_root.find(f".//{{{WORD_NS}}}t")
            self.assertEqual(text_node.text, " PT: Hello world ")
            self.assertEqual(
                text_node.get("{http://www.w3.org/XML/1998/namespace}space"),
                "preserve",
            )
            self.assertIsNotNone(document_root.find(f".//{{{WORD_NS}}}b"))
            self.assertEqual(
                document_root.find(f".//{{{WORD_NS}}}instrText").text,
                'HYPERLINK "https://example.com"',
            )

    def test_xlsx_translates_cell_text_and_comments_but_preserves_formulas_and_styles(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "English Sheet"
        worksheet["A1"] = "Hello workbook"
        worksheet["A1"].font = Font(bold=True, color="FF112233")
        worksheet["A1"].comment = Comment("Review this cell", "Reviewer")
        worksheet["A2"] = 7
        worksheet["A3"] = "=SUM(A2, 5)"
        source_stream = io.BytesIO()
        workbook.save(source_stream)

        xml_agent = _FakeXMLAgent()
        result = XLSXTranslationBot(xml_agent).translate_document(
            source_stream.getvalue(),
            document_name="scores.xlsx",
        )

        translated_workbook = load_workbook(
            io.BytesIO(result.content),
            data_only=False,
        )
        translated_sheet = translated_workbook["PT English Sheet"]
        self.assertEqual(translated_sheet["A1"].value, "PT: Hello workbook")
        self.assertEqual(translated_sheet["A1"].comment.text, "PT: Review this cell")
        self.assertEqual(translated_sheet["A1"].comment.author, "Reviewer")
        self.assertTrue(translated_sheet["A1"].font.bold)
        self.assertEqual(translated_sheet["A1"].font.color.rgb, "FF112233")
        self.assertEqual(translated_sheet["A2"].value, 7)
        self.assertEqual(translated_sheet["A3"].value, "=SUM(A2, 5)")
        self.assertEqual(translated_workbook.sheetnames, ["PT English Sheet"])
        self.assertEqual(len(xml_agent.calls), 2)
        self.assertIn("31 characters", xml_agent.calls[-1][4])

    def test_xlsx_translates_sheet_names_and_all_supported_sheet_references(self):
        workbook = Workbook()
        revenue_sheet = workbook.active
        revenue_sheet.title = "Revenue Data"
        revenue_sheet.append(["Month", "Revenue"])
        revenue_sheet.append(["January", 10])
        revenue_sheet.append(["February", 20])
        summary_sheet = workbook.create_sheet("Summary")
        summary_sheet["A1"] = "='Revenue Data'!B2"
        summary_sheet["B1"] = "Jump to data"
        summary_sheet["B1"].hyperlink = Hyperlink(
            ref="B1",
            location="'Revenue Data'!A1",
        )
        validation = DataValidation(
            type="list",
            formula1="'Revenue Data'!$A$2:$A$3",
        )
        summary_sheet.add_data_validation(validation)
        validation.add(summary_sheet["C1"])
        workbook.defined_names.add(
            DefinedName(
                "RevenueRange",
                attr_text="'Revenue Data'!$B$2:$B$3",
            )
        )
        chart = BarChart()
        chart.add_data(
            Reference(revenue_sheet, min_col=2, min_row=1, max_row=3),
            titles_from_data=True,
        )
        summary_sheet.add_chart(chart, "E1")
        source_stream = io.BytesIO()
        workbook.save(source_stream)
        source_content = _replace_zip_member(
            source_stream.getvalue(),
            "docProps/app.xml",
            (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<Properties xmlns="http://schemas.openxmlformats.org/'
                b'officeDocument/2006/extended-properties" '
                b'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/'
                b'2006/docPropsVTypes"><Application>Microsoft Excel</Application>'
                b'<TitlesOfParts><vt:vector size="2" baseType="lpstr">'
                b'<vt:lpstr>Revenue Data</vt:lpstr><vt:lpstr>Summary</vt:lpstr>'
                b'</vt:vector></TitlesOfParts></Properties>'
            ),
        )

        xml_agent = _MappingXMLAgent({
            "Revenue Data": "Dados de Receita",
            "Summary": "Resumo",
        })
        result = XLSXTranslationBot(xml_agent).translate_document(
            source_content,
            document_name="references.xlsx",
        )

        translated = load_workbook(io.BytesIO(result.content), data_only=False)
        self.assertEqual(translated.sheetnames, ["Dados de Receita", "Resumo"])
        translated_summary = translated["Resumo"]
        self.assertEqual(
            translated_summary["A1"].value,
            "='Dados de Receita'!B2",
        )
        self.assertEqual(
            translated_summary["B1"].hyperlink.location,
            "'Dados de Receita'!A1",
        )
        translated_validation = next(iter(translated_summary.data_validations.dataValidation))
        self.assertEqual(
            translated_validation.formula1,
            "'Dados de Receita'!$A$2:$A$3",
        )
        self.assertEqual(
            translated.defined_names["RevenueRange"].attr_text,
            "'Dados de Receita'!$B$2:$B$3",
        )
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            chart_xml = archive.read("xl/charts/chart1.xml").decode("utf-8")
            app_xml = archive.read("docProps/app.xml").decode("utf-8")
        self.assertIn("'Dados de Receita'!", chart_xml)
        self.assertNotIn("'Revenue Data'!", chart_xml)
        self.assertIn("Dados de Receita", app_xml)
        self.assertIn("Resumo", app_xml)
        self.assertNotIn("Revenue Data", app_xml)

    def test_xlsx_translates_sheet_name_when_workbook_has_no_cell_text(self):
        workbook = Workbook()
        workbook.active.title = "Sheet1"
        source_stream = io.BytesIO()
        workbook.save(source_stream)

        result = XLSXTranslationBot(
            _MappingXMLAgent({"Sheet1": "Planilha1"})
        ).translate_document(
            source_stream.getvalue(),
            document_name="empty.xlsx",
        )

        translated = load_workbook(io.BytesIO(result.content))
        self.assertEqual(result.outcome, "Translated")
        self.assertEqual(result.translated_nodes, 1)
        self.assertEqual(translated.sheetnames, ["Planilha1"])

    def test_xlsx_rejects_invalid_or_duplicate_translated_sheet_names(self):
        workbook = Workbook()
        workbook.active.title = "First"
        workbook.create_sheet("Second")
        source_stream = io.BytesIO()
        workbook.save(source_stream)

        with self.assertRaisesRegex(RuntimeError, "must be unique"):
            XLSXTranslationBot(
                _MappingXMLAgent({"First": "Resumo", "Second": "resumo"})
            ).translate_document(source_stream.getvalue())

    def test_xlsx_sheet_reference_rewriter_handles_quoted_unquoted_and_3d_refs(self):
        rewritten = XLSXTranslationBot._replace_sheet_references(
            (
                "=SUM(Sheet1:Sheet2!A1,'Sales Data'!B2,"
                "[Other.xlsx]Sheet1!C3,'O''Brien Data'!D4)"
            ),
            {
                "Sheet1": "Planilha1",
                "Sheet2": "Planilha2",
                "Sales Data": "Dados de Vendas",
                "O'Brien Data": "Dados O'Brien",
            },
        )

        self.assertEqual(
            rewritten,
            (
                "=SUM('Planilha1:Planilha2'!A1,'Dados de Vendas'!B2,"
                "'[Other.xlsx]Planilha1'!C3,'Dados O''Brien'!D4)"
            ),
        )

    def test_document_without_translatable_text_is_returned_unchanged(self):
        source = _zip_bytes({
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": (
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
                b'wordprocessingml/2006/main"><w:body/></w:document>'
            ),
        })

        result = DOCXTranslationBot(_FakeXMLAgent()).translate_document(source)

        self.assertEqual(result.outcome, "Skipped (No Translatable Text)")
        self.assertEqual(result.content, source)
        self.assertEqual(result.translated_nodes, 0)


class ControllerOfficeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "tests" / f"_office_controller_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_controller_delegates_docx_to_docx_bot_and_saves_rebuilt_bytes(self):
        source_path = self.root / "lesson.docx"
        source_path.write_bytes(b"original-docx")
        rebuilt = b"rebuilt-docx"
        bot = Mock()
        bot.extract_text.return_value = "Hello lesson"
        bot.translate_document.return_value = OfficeTranslationResult(
            rebuilt,
            translated_nodes=3,
            translated_parts=1,
            outcome="Translated",
        )
        controller = object.__new__(TranslationController)
        controller.workspace = Mock()
        controller.workspace.get_target_filepath.return_value = str(source_path)
        controller.bots = {"docx": bot}
        controller.auditor = Mock()
        controller.auditor.get_relevant_terms.return_value = {"lesson": "lição"}
        controller.scripture_checker = Mock()
        controller.scripture_checker.get_scriptures_for_text.return_value = {}
        controller._log = Mock()
        controller._record_gemini_translation_page = Mock()

        @contextmanager
        def successful_call(callback):
            callback()
            yield

        with patch("controller.track_successful_gemini_calls", successful_call):
            controller.process_file(str(source_path))

        self.assertEqual(source_path.read_bytes(), rebuilt)
        bot.extract_text.assert_called_once_with(b"original-docx")
        bot.translate_document.assert_called_once()
        controller._record_gemini_translation_page.assert_called_once_with(
            "lesson.docx",
            str(source_path),
        )
        self.assertTrue(
            any(
                "OfficeDocumentOutcome:" in call.args[0]
                and '"status": "Success"' in call.args[0]
                for call in controller._log.call_args_list
            )
        )

    def test_final_office_failure_generates_outcome_report_before_raising(self):
        controller = object.__new__(TranslationController)
        controller.filepaths = ["broken.docx"]
        controller.workspace = Mock(imscc_path="course.imscc")
        controller._log = Mock()
        controller.update_excel_dashboard = Mock(return_value="office-report.xlsx")
        controller.process_file = Mock(side_effect=RuntimeError("invalid package"))

        with self.assertRaisesRegex(
            RuntimeError,
            "Office outcome report: office-report.xlsx",
        ):
            controller.translate_files()

        self.assertEqual(controller.process_file.call_count, 2)
        controller.update_excel_dashboard.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
