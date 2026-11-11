import os
from pathlib import Path

import xlsxwriter


class GitHubTranslationReportGenerator:
    """Generate the focused three-sheet GitHub translation workbook."""

    REVIEW_STATUSES = ["Translated", "Student Reviewed", "Professionally Reviewed", "Failed"]
    PACKAGE_OPTIONS = [
        "Canvas", "External", "GitHub", "API Setting", "Technical Setup Instruction",
        "Video", "Image", "Codepen",
    ]
    HAS_TEXT_OPTIONS = ["- NA", "No", "Yes"]
    RESOURCE_STATUSES = ["To Do", "Done"]
    PLAN_OPTIONS = [
        "Find Equivalent", "Fix Link", "Recreate", "Remove", "Remove Text",
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
        todo = workbook.add_format({"border": 1, "bg_color": "#FFF2CC", "valign": "top"})
        done = workbook.add_format({"border": 1, "bg_color": "#C6E0B4", "valign": "top"})
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
        self._write_resources(
            workbook,
            asset_rows,
            header,
            cell,
            link,
            image_title,
            instruction,
            todo,
            done,
        )
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

    def _write_resources(
        self,
        workbook,
        rows,
        header,
        cell,
        link,
        resource_title,
        instruction,
        todo,
        done,
    ):
        sheet = workbook.add_worksheet("Resources")
        headers = [
            "Num", "Status", "Images (Copy from UniqueImages)", "Package",
            "Has Text", "Plan", "Target Language Link", "Resource Link", "Notes",
            "Alt Text EN", "Alt Text PT",
        ]
        sheet.merge_range(0, 0, 0, len(headers) - 1, "Resources", resource_title)
        sheet.set_row(0, 34)
        instructions = (
            "Review every listed resource and track the work with Status and Plan. Images must "
            "be checked for English text or US Locale formatted numbers. "
            "This includes screenshots of application menus, spreadsheet or document content, "
            "whiteboard writing, slide labels, etc. Decide whether the image needs to be "
            "recreated with translated text. Some external images may need to point to an "
            "alternate URL for the translated version of the course. Public external, GitHub, "
            "Canvas, and video resources are also listed here. API Setting means an instruction "
            "that directly configures, exposes, tests, documents, secures, stores data for, or "
            "deploys an API. Technical Setup Instruction means general tooling, repository, "
            "linting, project-setup, or workflow guidance not specifically about API behavior. "
            "Use Resource Link to "
            "open the video, file, image, or published instruction page that must be reviewed."
        )
        sheet.merge_range(1, 0, 1, len(headers) - 1, instructions, instruction)
        sheet.set_row(1, 52)
        sheet.write_row(2, 0, headers, header)
        sheet.freeze_panes(3, 0)
        widths = [8, 14, 58, 30, 14, 22, 48, 58, 45, 55, 55]
        for column, width in enumerate(widths):
            sheet.set_column(column, column, width)

        for index, row in enumerate(rows, start=1):
            row_index = index + 2
            sheet.write_number(row_index, 0, index, cell)
            status = str(row.get("status", "To Do") or "To Do")
            status_format = done if status == "Done" else todo
            sheet.write(row_index, 1, status, status_format)
            asset = row.get("asset_path", "")
            sheet.write(row_index, 2, asset, cell)
            sheet.write(row_index, 3, row.get("package", "GitHub"), cell)
            has_text = row.get("has_text", "")
            if has_text:
                sheet.write(row_index, 4, has_text, cell)
            else:
                sheet.write_blank(row_index, 4, None, cell)
            plan = row.get("plan", "")
            if plan:
                sheet.write(row_index, 5, plan, cell)
            else:
                sheet.write_blank(row_index, 5, None, cell)
            target_language_link = row.get(
                "target_language_link",
                row.get("tl_link", ""),
            )
            if target_language_link:
                sheet.write_url(
                    row_index,
                    6,
                    target_language_link,
                    link,
                    string=target_language_link,
                )
            else:
                sheet.write_blank(row_index, 6, None, cell)
            resource_link = row.get("resource_link", "")
            if resource_link:
                sheet.write_url(row_index, 7, resource_link, link, string=resource_link)
            else:
                sheet.write_blank(row_index, 7, None, cell)
            sheet.write(row_index, 8, row.get("notes", ""), cell)
            sheet.write(row_index, 9, row.get("alt_text_en", ""), cell)
            sheet.write(row_index, 10, row.get("alt_text_pt", ""), cell)

        last_row = max(3, len(rows) + 2)
        sheet.data_validation(3, 1, last_row, 1, {
            "validate": "list", "source": self.RESOURCE_STATUSES,
        })
        sheet.data_validation(3, 3, last_row, 3, {
            "validate": "list", "source": self.PACKAGE_OPTIONS,
        })
        sheet.data_validation(3, 4, last_row, 4, {
            "validate": "list", "source": self.HAS_TEXT_OPTIONS,
        })
        sheet.data_validation(3, 5, last_row, 5, {
            "validate": "list", "source": self.PLAN_OPTIONS,
        })
        for status, status_format in (("To Do", todo), ("Done", done)):
            sheet.conditional_format(3, 1, last_row, 1, {
                "type": "cell",
                "criteria": "==",
                "value": f'"{status}"',
                "format": status_format,
            })
        if rows:
            sheet.autofilter(2, 0, len(rows) + 2, len(headers) - 1)
