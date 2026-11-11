from bots.office_xml_bot import OfficeXMLRoundTripBot


_SPREADSHEET_NAMESPACES = {
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "http://purl.oclc.org/ooxml/spreadsheetml/main",
}


class XLSXTranslationBot(OfficeXMLRoundTripBot):
    package_label = "XLSX"
    required_main_part = "xl/workbook.xml"

    def _is_candidate_part(self, part_name: str) -> bool:
        return (
            part_name == "xl/sharedStrings.xml"
            or part_name.startswith("xl/worksheets/")
            or part_name.startswith("xl/comments")
        ) and part_name.endswith(".xml")

    def _is_translatable_node(self, part_name, node, ancestors) -> bool:
        if not isinstance(node.tag, str):
            return False
        namespace, local_name = self._expanded_name_parts(node.tag)
        if local_name != "t" or namespace not in _SPREADSHEET_NAMESPACES:
            return False

        ancestor_names = [self._local_name(ancestor) for ancestor in ancestors]
        if "rPh" in ancestor_names:
            return False
        if part_name == "xl/sharedStrings.xml":
            return "si" in ancestor_names
        if part_name.startswith("xl/worksheets/"):
            return "is" in ancestor_names
        if part_name.startswith("xl/comments"):
            return "text" in ancestor_names
        return False
