import os
from pathlib import Path

import xlsxwriter


class GitHubTranslationReportGenerator:
    """Generate the focused three-sheet GitHub translation workbook."""

    REVIEW_STATUSES = ["Translated", "Student Reviewed", "Professionally Reviewed", "Failed"]
    PACKAGE_OPTIONS = ["BrightSpot", "Canvas", "External", "GitHub", "LLDOC"]
    HAS_TEXT_OPTIONS = ["- NA", "No", "Yes"]
    PLAN_OPTIONS = [
        "Find Equivalent", "Recreate", "Remove", "Remove Text",
        "Request Translate", "Use Current",
    ]

    def __init__(self, reports_dir):
        self.reports_dir = Path(reports_dir)

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = "".join(character for character in name if character.isalnum() or character in " -_").strip()
        return safe or "GitHub Course"

    def generate(self, report_name, review_rows, variable_rows, asset_rows):
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.reports_dir / f"{self._safe_name(report_name)} GitHub Translation Report.xlsx"
        workbook = xlsxwriter.Workbook(str(report_path))

        header = workbook.add_format({
            "bold": True, "font_color": "white", "bg_color": "#34495E",
            "border": 1, "align": "center", "valign": "vcenter",
        })
        cell = workbook.add_format({"border": 1, "valign": "top"})
        link = workbook.add_format({"border": 1, "font_color": "blue", "underline": 1, "valign": "top"})
        translated = workbook.add_format({"border": 1, "bg_color": "#D9D9D9", "valign": "top"})
        student = workbook.add_format({"border": 1, "bg_color": "#FFF2CC", "valign": "top"})
        professional = workbook.add_format({"border": 1, "bg_color": "#C6E0B4", "valign": "top"})
        failed = workbook.add_format({"border": 1, "bg_color": "#F4CCCC", "font_color": "#990000", "valign": "top"})
        duplicate = workbook.add_format({"bg_color": "#FFE082", "font_color": "#9C5700"})
        image_title = workbook.add_format({
            "bold": True, "font_size": 24, "font_color": "white",
            "bg_color": "#087EC1", "align": "center", "valign": "vcenter",
        })
        instruction = workbook.add_format({"text_wrap": True, "valign": "top", "border": 1})

        self._write_reviewing(
            workbook, review_rows, header, cell, link,
            translated, student, professional, failed,
        )
        self._write_variables(workbook, variable_rows, header, cell, duplicate)
        self._write_assets(workbook, asset_rows, header, cell, link, image_title, instruction)
        workbook.close()
        return str(report_path)

    def _write_reviewing(self, workbook, rows, header, cell, link, translated, student, professional, failed):
        sheet = workbook.add_worksheet("Reviewing")
        headers = ["Page Name", "Type", "Link EN", "Link PT", "Status", "Notes / Error"]
        sheet.write_row(0, 0, headers, header)
        sheet.freeze_panes(1, 0)
        sheet.set_column("A:A", 55)
        sheet.set_column("B:B", 16)
        sheet.set_column("C:D", 50)
        sheet.set_column("E:E", 24)
        sheet.set_column("F:F", 60)
        for row_index, row in enumerate(rows, start=1):
            sheet.write(row_index, 0, row.get("page_name", ""), cell)
            sheet.write(row_index, 1, row.get("type", ""), cell)
            for column, key in ((2, "link_en"), (3, "link_pt")):
                value = row.get(key, "")
                if value:
                    sheet.write_url(row_index, column, value, link, string=value)
                else:
                    sheet.write_blank(row_index, column, None, cell)
            status = row.get("status", "Translated")
            status_format = failed if status == "Failed" else translated
            sheet.write(row_index, 4, status, status_format)
            sheet.write(row_index, 5, row.get("notes", ""), cell)

        last_row = max(1, len(rows))
        sheet.data_validation(1, 4, last_row, 4, {
            "validate": "list", "source": self.REVIEW_STATUSES,
            "input_title": "Review Status",
        })
        for status, status_format in (
            ("Translated", translated),
            ("Student Reviewed", student),
            ("Professionally Reviewed", professional),
            ("Failed", failed),
        ):
            sheet.conditional_format(1, 4, last_row, 4, {
                "type": "cell", "criteria": "==", "value": f'"{status}"',
                "format": status_format,
            })
        if rows:
            sheet.autofilter(0, 0, len(rows), len(headers) - 1)

    @staticmethod
    def _write_variables(workbook, rows, header, cell, duplicate):
        sheet = workbook.add_worksheet("Variables")
        headers = ["Page Title", "Context Summary", "Variable EN", "Variable PT", "Source File"]
        sheet.write_row(0, 0, headers, header)
        sheet.freeze_panes(1, 0)
        sheet.set_column("A:A", 40)
        sheet.set_column("B:B", 70)
        sheet.set_column("C:D", 28)
        sheet.set_column("E:E", 55)
        for row_index, row in enumerate(rows, start=1):
            sheet.write(row_index, 0, row.get("page_title", ""), cell)
            sheet.write(row_index, 1, row.get("context_summary", ""), cell)
            sheet.write(row_index, 2, row.get("variable_en", ""), cell)
            sheet.write(row_index, 3, row.get("variable_pt", ""), cell)
            sheet.write(row_index, 4, row.get("source_file", ""), cell)
        if rows:
            last_excel_row = len(rows) + 1
            sheet.conditional_format(1, 2, len(rows), 2, {
                "type": "formula",
                "criteria": f'=AND(C2<>"",COUNTIF($C$2:$C${last_excel_row},C2)>1)',
                "format": duplicate,
            })
            sheet.autofilter(0, 0, len(rows), len(headers) - 1)

    def _write_assets(self, workbook, rows, header, cell, link, image_title, instruction):
        sheet = workbook.add_worksheet("Images and Files")
        headers = [
            "In U.Images", "Images (Copy from UniqueImages)", "Package", "Has Text",
            "Plan", "TL Link", "Notes", "Num", "Alt Text EN", "Alt Text PT",
        ]
        sheet.merge_range(0, 0, 0, len(headers) - 1, "Images", image_title)
        sheet.set_row(0, 34)
        instructions = (
            "All images need to be checked for English text or US Locale formatted numbers. "
            "This includes screenshots of application menus, spreadsheet or document content, "
            "whiteboard writing, slide labels, etc. Decide whether the image needs to be "
            "recreated with translated text. Some external images may need to point to an "
            "alternate URL for the translated version of the course."
        )
        sheet.merge_range(1, 0, 1, len(headers) - 1, instructions, instruction)
        sheet.set_row(1, 34)
        sheet.write_row(2, 0, headers, header)
        sheet.freeze_panes(3, 0)
        widths = [12, 58, 14, 14, 22, 48, 45, 8, 55, 55]
        for column, width in enumerate(widths):
            sheet.set_column(column, column, width)

        for index, row in enumerate(rows, start=1):
            row_index = index + 2
            # U.Images deliberately remains blank until an authoritative Unique
            # Images catalog is supplied.
            sheet.write_blank(row_index, 0, None, cell)
            asset = row.get("asset_path", "")
            sheet.write(row_index, 1, asset, cell)
            sheet.write(row_index, 2, "GitHub", cell)
            sheet.write_blank(row_index, 3, None, cell)
            sheet.write_blank(row_index, 4, None, cell)
            tl_link = row.get("tl_link", "")
            if tl_link:
                sheet.write_url(row_index, 5, tl_link, link, string=tl_link)
            else:
                sheet.write_blank(row_index, 5, None, cell)
            sheet.write(row_index, 6, row.get("notes", ""), cell)
            sheet.write_number(row_index, 7, index, cell)
            sheet.write(row_index, 8, row.get("alt_text_en", ""), cell)
            sheet.write(row_index, 9, row.get("alt_text_pt", ""), cell)

        last_row = max(3, len(rows) + 2)
        sheet.data_validation(3, 2, last_row, 2, {
            "validate": "list", "source": self.PACKAGE_OPTIONS,
        })
        sheet.data_validation(3, 3, last_row, 3, {
            "validate": "list", "source": self.HAS_TEXT_OPTIONS,
        })
        sheet.data_validation(3, 4, last_row, 4, {
            "validate": "list", "source": self.PLAN_OPTIONS,
        })
        if rows:
            sheet.autofilter(2, 0, len(rows) + 2, len(headers) - 1)
