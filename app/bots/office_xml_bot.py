import io
import html
import re
import threading
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass


_XML_DECLARATION = re.compile(br"^\s*(<\?xml[^?]*\?>)")
_LEADING_WHITESPACE = re.compile(r"^\s*")
_TRAILING_WHITESPACE = re.compile(r"\s*$")


@dataclass(frozen=True)
class OfficeTranslationResult:
    content: bytes
    translated_nodes: int
    translated_parts: int
    outcome: str


@dataclass
class _TextReference:
    item_id: str
    node: ET.Element
    leading_whitespace: str
    trailing_whitespace: str


@dataclass
class _ParsedPart:
    name: str
    original_content: bytes
    root: ET.Element
    namespaces: list[tuple[str, str]]
    structural_signature: tuple
    references: list[_TextReference]


class OfficeXMLRoundTripBot:
    """Translate selected Office Open XML text while preserving the OPC package."""

    package_label = "Office"
    required_main_part = ""
    _namespace_lock = threading.Lock()

    def __init__(self, xml_agent, log_func=None):
        self.xml_agent = xml_agent
        self.log_func = log_func

    def _log(self, message: str):
        if self.log_func:
            self.log_func(f"[{self.__class__.__name__}] {message}")

    @staticmethod
    def _expanded_name_parts(name: str) -> tuple[str, str]:
        if name.startswith("{") and "}" in name:
            namespace, local_name = name[1:].split("}", 1)
            return namespace, local_name
        return "", name

    @classmethod
    def _local_name(cls, node: ET.Element) -> str:
        if not isinstance(node.tag, str):
            return ""
        return cls._expanded_name_parts(node.tag)[1]

    def _is_candidate_part(self, part_name: str) -> bool:
        raise NotImplementedError

    def _is_translatable_node(
        self,
        part_name: str,
        node: ET.Element,
        ancestors: tuple[ET.Element, ...],
    ) -> bool:
        raise NotImplementedError

    @staticmethod
    def _namespace_declarations(content: bytes) -> list[tuple[str, str]]:
        declarations = []
        seen = set()
        for _event, declaration in ET.iterparse(
            io.BytesIO(content),
            events=("start-ns",),
        ):
            prefix, uri = declaration
            normalized = (prefix or "", uri)
            if normalized not in seen:
                declarations.append(normalized)
                seen.add(normalized)
        return declarations

    @classmethod
    def _register_namespaces(cls, namespaces: list[tuple[str, str]]):
        for prefix, uri in namespaces:
            if prefix != "xml":
                try:
                    ET.register_namespace(prefix, uri)
                except ValueError:
                    # ElementTree reserves generated prefixes such as ns0.
                    # The namespace URI remains intact with a generated prefix.
                    continue

    @classmethod
    def _parse_xml(
        cls,
        part_name: str,
        content: bytes,
    ) -> tuple[ET.Element, list[tuple[str, str]]]:
        try:
            namespaces = cls._namespace_declarations(content)
            parser = ET.XMLParser(
                target=ET.TreeBuilder(insert_comments=True, insert_pis=True)
            )
            with cls._namespace_lock:
                cls._register_namespaces(namespaces)
                root = ET.fromstring(content, parser=parser)
            return root, namespaces
        except ET.ParseError as exc:
            raise RuntimeError(
                f"Invalid XML in {part_name}: {exc}"
            ) from exc

    @classmethod
    def _serialize_xml(
        cls,
        original_content: bytes,
        root: ET.Element,
        namespaces: list[tuple[str, str]],
    ) -> bytes:
        with cls._namespace_lock:
            cls._register_namespaces(namespaces)
            serialized = ET.tostring(
                root,
                encoding="utf-8",
                short_empty_elements=True,
            )
        serialized = cls._restore_namespace_declarations(serialized, namespaces)
        declaration = _XML_DECLARATION.match(original_content)
        if declaration:
            return declaration.group(1) + b"\n" + serialized
        return serialized

    @staticmethod
    def _restore_namespace_declarations(
        serialized: bytes,
        namespaces: list[tuple[str, str]],
    ) -> bytes:
        """Keep declarations used by mc:Ignorable and similar Office metadata."""
        quote = None
        root_tag_end = -1
        for index, byte in enumerate(serialized):
            if byte in (ord('"'), ord("'")):
                if quote is None:
                    quote = byte
                elif quote == byte:
                    quote = None
            elif byte == ord(">") and quote is None:
                root_tag_end = index
                break
        if root_tag_end < 0:
            return serialized

        root_start = serialized[:root_tag_end]
        additions = []
        for prefix, uri in namespaces:
            if prefix == "xml":
                continue
            attribute_name = b"xmlns" + (
                b":" + prefix.encode("utf-8") if prefix else b""
            )
            if re.search(rb"\s" + re.escape(attribute_name) + rb"\s*=", root_start):
                continue
            escaped_uri = html.escape(uri, quote=True).encode("utf-8")
            additions.append(b" " + attribute_name + b'="' + escaped_uri + b'"')

        if not additions:
            return serialized
        insertion_point = root_tag_end
        if serialized[root_tag_end - 1:root_tag_end] == b"/":
            insertion_point -= 1
        return (
            serialized[:insertion_point]
            + b"".join(additions)
            + serialized[insertion_point:]
        )

    def _walk_nodes(
        self,
        part_name: str,
        node: ET.Element,
        ancestors: tuple[ET.Element, ...] = (),
    ):
        yield node, ancestors
        for child in list(node):
            yield from self._walk_nodes(part_name, child, ancestors + (node,))

    def _structural_signature(self, part_name: str, root: ET.Element) -> tuple:
        def signature(node: ET.Element, ancestors: tuple[ET.Element, ...]):
            if not isinstance(node.tag, str):
                return (node.tag, node.text, node.tail)
            translatable = self._is_translatable_node(
                part_name,
                node,
                ancestors,
            )
            return (
                node.tag,
                tuple(sorted(node.attrib.items())),
                "<TRANSLATABLE_TEXT>" if translatable else node.text,
                node.tail,
                tuple(
                    signature(child, ancestors + (node,))
                    for child in list(node)
                ),
            )

        return signature(root, ())

    def _parse_package(self, package_content: bytes) -> tuple[list, dict[str, bytes]]:
        try:
            with zipfile.ZipFile(io.BytesIO(package_content), "r") as archive:
                infos = archive.infolist()
                if archive.testzip() is not None:
                    raise RuntimeError("The Office package contains a corrupt ZIP member.")
                members = {info.filename: archive.read(info) for info in infos}
        except (zipfile.BadZipFile, OSError) as exc:
            raise RuntimeError(
                f"The {self.package_label} file is not a valid Office Open XML package."
            ) from exc

        names = [info.filename for info in infos]
        if "[Content_Types].xml" not in names or self.required_main_part not in names:
            raise RuntimeError(
                f"The {self.package_label} package is missing required Office XML parts."
            )
        return infos, members

    def _collect_parts(
        self,
        members: dict[str, bytes],
    ) -> tuple[list[_ParsedPart], dict[str, str]]:
        parsed_parts = []
        text_items = {}
        item_index = 0

        for part_name, content in members.items():
            if not self._is_candidate_part(part_name):
                continue
            root, namespaces = self._parse_xml(part_name, content)
            structural_signature = self._structural_signature(part_name, root)
            references = []
            for node, ancestors in self._walk_nodes(part_name, root):
                if not self._is_translatable_node(part_name, node, ancestors):
                    continue
                source_text = node.text or ""
                if not source_text.strip():
                    continue
                leading = _LEADING_WHITESPACE.match(source_text).group(0)
                trailing = _TRAILING_WHITESPACE.search(source_text).group(0)
                end_index = len(source_text) - len(trailing) if trailing else len(source_text)
                translatable_text = source_text[len(leading):end_index]
                if not translatable_text:
                    continue

                item_id = f"office_{item_index}"
                item_index += 1
                # Office text nodes are plain text, not embedded markup. Escape
                # delimiters so values such as "5 < 10" cannot break the XML-like
                # translate_item envelope used by XMLTranslationAgent.
                text_items[item_id] = html.escape(
                    translatable_text,
                    quote=False,
                )
                references.append(
                    _TextReference(item_id, node, leading, trailing)
                )

            if references:
                parsed_parts.append(
                    _ParsedPart(
                        part_name,
                        content,
                        root,
                        namespaces,
                        structural_signature,
                        references,
                    )
                )

        return parsed_parts, text_items

    def extract_text(self, package_content: bytes) -> str:
        _infos, members = self._parse_package(package_content)
        _parts, text_items = self._collect_parts(members)
        return "\n".join(html.unescape(text) for text in text_items.values())

    def _rebuild_package(
        self,
        infos: list,
        members: dict[str, bytes],
        replacements: dict[str, bytes],
    ) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for info in infos:
                archive.writestr(info, replacements.get(info.filename, members[info.filename]))
        return output.getvalue()

    def _validate_rebuilt_package(
        self,
        original_infos: list,
        original_members: dict[str, bytes],
        rebuilt_content: bytes,
        parsed_parts: list[_ParsedPart],
    ):
        rebuilt_infos, rebuilt_members = self._parse_package(rebuilt_content)
        original_names = [info.filename for info in original_infos]
        rebuilt_names = [info.filename for info in rebuilt_infos]
        if rebuilt_names != original_names:
            raise RuntimeError("The rebuilt Office package changed its ZIP member structure.")

        translated_names = {part.name for part in parsed_parts}
        for name, content in original_members.items():
            if name not in translated_names and rebuilt_members[name] != content:
                raise RuntimeError(
                    f"The rebuild unexpectedly changed non-translatable part {name}."
                )

        parts_by_name = {part.name: part for part in parsed_parts}
        for name in translated_names:
            rebuilt_root, _namespaces = self._parse_xml(name, rebuilt_members[name])
            rebuilt_signature = self._structural_signature(name, rebuilt_root)
            if rebuilt_signature != parts_by_name[name].structural_signature:
                raise RuntimeError(
                    f"The rebuild changed protected XML structure in {name}."
                )

    def translate_document(
        self,
        package_content: bytes,
        relevant_glossary: dict = None,
        relevant_scriptures: dict = None,
        document_name: str = "Office document",
    ) -> OfficeTranslationResult:
        infos, members = self._parse_package(package_content)
        parsed_parts, text_items = self._collect_parts(members)
        if not text_items:
            self._log(f"No translatable text found in {document_name}.")
            return OfficeTranslationResult(
                package_content,
                translated_nodes=0,
                translated_parts=0,
                outcome="Skipped (No Translatable Text)",
            )

        if not hasattr(self.xml_agent, "translate_text_items"):
            raise RuntimeError(
                "The configured XML translation agent cannot translate Office text items."
            )

        self._log(
            f"Sending {len(text_items)} text node(s) from {len(parsed_parts)} "
            f"XML part(s) through XMLTranslationAgent for {document_name}."
        )
        translated_items = self.xml_agent.translate_text_items(
            text_items,
            relevant_glossary,
            relevant_scriptures,
            context_label=document_name,
        )
        missing_items = sorted(set(text_items) - set(translated_items))
        if missing_items:
            raise RuntimeError(
                "XMLTranslationAgent omitted Office text item(s): "
                + ", ".join(missing_items[:10])
            )

        replacements = {}
        for part in parsed_parts:
            for reference in part.references:
                translated_text = html.unescape(
                    translated_items[reference.item_id]
                )
                reference.node.text = (
                    reference.leading_whitespace
                    + translated_text
                    + reference.trailing_whitespace
                )
            if self._structural_signature(part.name, part.root) != part.structural_signature:
                raise RuntimeError(
                    f"Translation changed protected XML structure in {part.name}."
                )
            replacements[part.name] = self._serialize_xml(
                part.original_content,
                part.root,
                part.namespaces,
            )

        rebuilt_content = self._rebuild_package(infos, members, replacements)
        self._validate_rebuilt_package(
            infos,
            members,
            rebuilt_content,
            parsed_parts,
        )
        self._log(
            f"Rebuilt and validated {document_name}: {len(text_items)} text "
            f"node(s) across {len(parsed_parts)} XML part(s)."
        )
        return OfficeTranslationResult(
            rebuilt_content,
            translated_nodes=len(text_items),
            translated_parts=len(parsed_parts),
            outcome="Translated",
        )
