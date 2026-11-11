from bots.office_xml_bot import OfficeXMLRoundTripBot


_WORDPROCESSING_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
}
_DRAWINGML_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}


class DOCXTranslationBot(OfficeXMLRoundTripBot):
    package_label = "DOCX"
    required_main_part = "word/document.xml"

    def _is_candidate_part(self, part_name: str) -> bool:
        return part_name.startswith("word/") and part_name.endswith(".xml")

    def _is_translatable_node(self, part_name, node, ancestors) -> bool:
        del part_name, ancestors
        if not isinstance(node.tag, str):
            return False
        namespace, local_name = self._expanded_name_parts(node.tag)
        return local_name == "t" and namespace in (
            _WORDPROCESSING_NAMESPACES | _DRAWINGML_NAMESPACES
        )
