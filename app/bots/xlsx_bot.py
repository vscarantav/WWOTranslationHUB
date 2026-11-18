import html
import re

from bots.office_xml_bot import OfficeTranslationResult, OfficeXMLRoundTripBot


_SPREADSHEET_NAMESPACES = {
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "http://purl.oclc.org/ooxml/spreadsheetml/main",
}

_INVALID_SHEET_TITLE_CHARS = re.compile(r"[\\/*?:\[\]]")
_QUOTED_SHEET_REFERENCE = re.compile(r"'((?:[^']|'')+)'(?=!)")
_UNQUOTED_SHEET_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_.'\]\u0080-\uffff])"
    r"(?P<external>\[[^\]\r\n]+\])?"
    r"(?P<sheets>[A-Za-z0-9_.\u0080-\uffff]+"
    r"(?::[A-Za-z0-9_.\u0080-\uffff]+)?)(?=!)"
)
_REFERENCE_TEXT_LOCAL_NAMES = {
    "f",
    "formula",
    "formula1",
    "formula2",
    "definedName",
    "calculatedColumnFormula",
    "totalsRowFormula",
}
_REFERENCE_ATTRIBUTE_LOCAL_NAMES = {
    "formula",
    "formula1",
    "formula2",
    "location",
    "refersTo",
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

    @classmethod
    def _sheet_nodes(cls, workbook_root):
        return [
            node
            for node in workbook_root.iter()
            if isinstance(node.tag, str)
            and cls._expanded_name_parts(node.tag)[0] in _SPREADSHEET_NAMESPACES
            and cls._local_name(node) == "sheet"
        ]

    def _extract_sheet_titles(self, members: dict[str, bytes]) -> list[str]:
        workbook_root, _namespaces = self._parse_xml(
            "xl/workbook.xml",
            members["xl/workbook.xml"],
        )
        titles = [node.get("name", "") for node in self._sheet_nodes(workbook_root)]
        if not titles or any(not title for title in titles):
            raise RuntimeError("The XLSX workbook contains a worksheet without a valid name.")
        return titles

    def extract_text(self, package_content: bytes) -> str:
        _infos, members = self._parse_package(package_content)
        content_text = super().extract_text(package_content)
        titles = self._extract_sheet_titles(members)
        return "\n".join(part for part in (content_text, *titles) if part)

    @staticmethod
    def _title_lookup(title_map: dict[str, str]) -> dict[str, str]:
        return {source.casefold(): target for source, target in title_map.items()}

    @classmethod
    def _replace_sheet_references(cls, value: str, title_map: dict[str, str]) -> str:
        if not value:
            return value
        lookup = cls._title_lookup(title_map)

        def replace_quoted(match):
            token = match.group(1).replace("''", "'")
            external = ""
            sheet_expression = token
            if token.startswith("[") and "]" in token:
                boundary = token.index("]") + 1
                external = token[:boundary]
                sheet_expression = token[boundary:]
            source_titles = sheet_expression.split(":")
            translated_titles = [
                lookup.get(source.casefold(), source) for source in source_titles
            ]
            if translated_titles == source_titles:
                return match.group(0)
            translated_token = external + ":".join(translated_titles)
            return "'" + translated_token.replace("'", "''") + "'"

        def replace_unquoted(match):
            source_titles = match.group("sheets").split(":")
            translated_titles = [
                lookup.get(source.casefold(), source) for source in source_titles
            ]
            if translated_titles == source_titles:
                return match.group(0)
            translated_token = (match.group("external") or "") + ":".join(
                translated_titles
            )
            return "'" + translated_token.replace("'", "''") + "'"

        value = _QUOTED_SHEET_REFERENCE.sub(replace_quoted, value)
        return _UNQUOTED_SHEET_REFERENCE.sub(replace_unquoted, value)

    @classmethod
    def _translated_title_for(cls, value: str, title_map: dict[str, str]):
        return cls._title_lookup(title_map).get(value.casefold())

    def _rewrite_reference_tree(self, root, title_map: dict[str, str]) -> bool:
        changed = False
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            local_name = self._local_name(node)
            if local_name in _REFERENCE_TEXT_LOCAL_NAMES and node.text:
                translated_text = self._replace_sheet_references(node.text, title_map)
                if translated_text != node.text:
                    node.text = translated_text
                    changed = True

            for attribute_name, attribute_value in list(node.attrib.items()):
                attribute_local_name = self._expanded_name_parts(attribute_name)[1]
                translated_value = attribute_value
                if attribute_local_name == "sheet":
                    translated_value = (
                        self._translated_title_for(attribute_value, title_map)
                        or attribute_value
                    )
                elif attribute_local_name in _REFERENCE_ATTRIBUTE_LOCAL_NAMES:
                    translated_value = self._replace_sheet_references(
                        attribute_value,
                        title_map,
                    )
                if translated_value != attribute_value:
                    node.set(attribute_name, translated_value)
                    changed = True
        return changed

    def _rewrite_sheet_title_parts(
        self,
        members: dict[str, bytes],
        title_map: dict[str, str],
    ) -> dict[str, bytes]:
        replacements = {}
        remaining_document_titles = self._title_lookup(title_map)
        for part_name, content in members.items():
            if part_name == "docProps/app.xml":
                root, namespaces = self._parse_xml(part_name, content)
                changed = False
                for node in root.iter():
                    if not isinstance(node.tag, str) or self._local_name(node) != "lpstr":
                        continue
                    translated_title = remaining_document_titles.pop(
                        (node.text or "").casefold(),
                        None,
                    )
                    if translated_title and translated_title != node.text:
                        node.text = translated_title
                        changed = True
                if changed:
                    replacements[part_name] = self._serialize_xml(
                        content,
                        root,
                        namespaces,
                    )
                continue

            if not (part_name == "xl/workbook.xml" or (
                part_name.startswith("xl/")
                and part_name.endswith(".xml")
                and part_name != "xl/sharedStrings.xml"
                and not part_name.startswith("xl/comments")
            )):
                continue

            root, namespaces = self._parse_xml(part_name, content)
            changed = self._rewrite_reference_tree(root, title_map)
            if part_name == "xl/workbook.xml":
                for sheet_node in self._sheet_nodes(root):
                    source_title = sheet_node.get("name", "")
                    translated_title = self._translated_title_for(
                        source_title,
                        title_map,
                    )
                    if translated_title and translated_title != source_title:
                        sheet_node.set("name", translated_title)
                        changed = True
            if changed:
                replacements[part_name] = self._serialize_xml(
                    content,
                    root,
                    namespaces,
                )
        return replacements

    @staticmethod
    def _validate_translated_titles(title_map: dict[str, str]):
        translated_titles = list(title_map.values())
        for source_title, translated_title in title_map.items():
            if not translated_title:
                raise RuntimeError(
                    f"Worksheet title translation is empty for {source_title!r}."
                )
            if len(translated_title) > 31:
                raise RuntimeError(
                    "Worksheet title translation exceeds Excel's 31-character limit: "
                    f"{source_title!r} -> {translated_title!r}."
                )
            if _INVALID_SHEET_TITLE_CHARS.search(translated_title):
                raise RuntimeError(
                    "Worksheet title translation contains an Excel-invalid character: "
                    f"{source_title!r} -> {translated_title!r}."
                )
            if translated_title.startswith("'") or translated_title.endswith("'"):
                raise RuntimeError(
                    "Worksheet title translation cannot begin or end with an apostrophe: "
                    f"{source_title!r} -> {translated_title!r}."
                )
        if len({title.casefold() for title in translated_titles}) != len(
            translated_titles
        ):
            raise RuntimeError(
                "Worksheet title translations must be unique within the workbook."
            )

    def _translate_sheet_titles(
        self,
        package_content: bytes,
        relevant_glossary: dict,
        document_name: str,
    ) -> tuple[bytes, int]:
        infos, members = self._parse_package(package_content)
        source_titles = self._extract_sheet_titles(members)
        title_items = {
            f"worksheet_title_{index}": html.escape(title, quote=False)
            for index, title in enumerate(source_titles)
        }
        translated_items = self.xml_agent.translate_text_items(
            title_items,
            relevant_glossary,
            None,
            context_label=f"{document_name} worksheet tab names",
            additional_constraints=(
                "Translate each item as a concise worksheet tab title. Return only the "
                "translated title. Every title must be non-empty, natural in the target "
                "language, unique among these items, no more than 31 characters, and must "
                "not contain \\, /, *, ?, :, [, or ]. Translate generic default names "
                "such as Sheet1 as well."
            ),
        )
        missing_items = sorted(set(title_items) - set(translated_items))
        if missing_items:
            raise RuntimeError(
                "XMLTranslationAgent omitted worksheet title item(s): "
                + ", ".join(missing_items)
            )
        title_map = {
            source_title: html.unescape(
                translated_items[f"worksheet_title_{index}"]
            ).strip()
            for index, source_title in enumerate(source_titles)
        }
        self._validate_translated_titles(title_map)
        replacements = self._rewrite_sheet_title_parts(members, title_map)
        if "xl/workbook.xml" not in replacements:
            raise RuntimeError("Worksheet tab names were not updated in xl/workbook.xml.")
        rebuilt_content = self._rebuild_package(infos, members, replacements)

        rebuilt_infos, rebuilt_members = self._parse_package(rebuilt_content)
        if [info.filename for info in rebuilt_infos] != [info.filename for info in infos]:
            raise RuntimeError("Worksheet title translation changed the XLSX ZIP structure.")
        expected_titles = [title_map[title] for title in source_titles]
        if self._extract_sheet_titles(rebuilt_members) != expected_titles:
            raise RuntimeError("Worksheet tab names failed XLSX rebuild verification.")
        for part_name, content in members.items():
            if part_name not in replacements and rebuilt_members[part_name] != content:
                raise RuntimeError(
                    "Worksheet title translation unexpectedly changed "
                    f"{part_name}."
                )
        return rebuilt_content, len(replacements)

    def translate_document(
        self,
        package_content: bytes,
        relevant_glossary: dict = None,
        relevant_scriptures: dict = None,
        document_name: str = "Excel workbook",
    ) -> OfficeTranslationResult:
        content_result = super().translate_document(
            package_content,
            relevant_glossary,
            relevant_scriptures,
            document_name,
        )
        rebuilt_content, title_part_count = self._translate_sheet_titles(
            content_result.content,
            relevant_glossary,
            document_name,
        )
        _original_infos, original_members = self._parse_package(package_content)
        _rebuilt_infos, rebuilt_members = self._parse_package(rebuilt_content)
        translated_part_count = sum(
            1
            for name, content in original_members.items()
            if name.endswith(".xml") and rebuilt_members[name] != content
        )
        translated_nodes = content_result.translated_nodes + len(
            self._extract_sheet_titles(original_members)
        )
        self._log(
            f"Translated and validated {translated_nodes} text node(s), including "
            f"worksheet tab names, across {translated_part_count} XML part(s) in "
            f"{document_name}."
        )
        return OfficeTranslationResult(
            rebuilt_content,
            translated_nodes=translated_nodes,
            translated_parts=max(translated_part_count, title_part_count),
            outcome="Translated",
        )
