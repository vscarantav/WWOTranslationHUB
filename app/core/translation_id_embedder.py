"""Late, deterministic Translation ID embedding for translated IMSCC content."""

from __future__ import annotations

import html
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Mapping
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from core.translation_id_registry import (
    VISIBLE_MARKER_RE,
    TranslationIdRegistry,
    TranslationIdRegistryError,
)


class TranslationIdEmbeddingError(RuntimeError):
    """Raised when local embedding would be ambiguous or corrupt content."""


class TranslationIdEmbedder:
    """Embed registered IDs after model-driven processing and validate them."""

    def __init__(
        self,
        course_root: os.PathLike[str] | str,
        registry: TranslationIdRegistry | Mapping[str, Any] | os.PathLike[str] | str,
        language: str | None = None,
        target_course_id: str | None = None,
    ) -> None:
        self.course_root = Path(course_root).resolve()
        if not self.course_root.is_dir():
            raise TranslationIdEmbeddingError(
                f"IMSCC workspace does not exist: {self.course_root}"
            )
        self.registry = self._coerce_registry(registry)
        self.language = str(language).upper() if language else None
        if self.language and self.language not in self.registry.languages:
            raise TranslationIdEmbeddingError(
                f"Unsupported registry language for local embedding: {language}"
            )
        self.target_course_id = str(target_course_id) if target_course_id else None

    def embed_all(self) -> Dict[str, Any]:
        results = []
        for item in self.registry.items:
            if item.get("retired"):
                item["local_embed_status"] = "Skipped"
                item["detail"] = "Registry item is retired."
                results.append(self._result(item, "Skipped", item["detail"]))
                continue
            placement = item.get("placement", "")
            try:
                if placement in {
                    "html_body_end",
                    "assignment_html_body_end",
                    "discussion_visible_text_end",
                    "announcement_visible_text_end",
                }:
                    status = self._embed_html_or_topic(item)
                elif placement == "quiz_description":
                    status = self._embed_quiz_description(item)
                elif placement == "question_bank_title":
                    status = self._embed_question_bank_title(item)
                elif placement == "docx_document_end_and_canvas_display_filename":
                    status = self._embed_docx(item)
                elif placement in {
                    "canvas_display_filename",
                    "module_meta_audit",
                    "module_item_audit",
                    "registry_only",
                }:
                    status = "Skipped by design"
                else:
                    raise TranslationIdEmbeddingError(
                        f"Unknown embedding placement {placement!r}."
                    )
            except Exception as error:
                item["local_embed_status"] = "Conflict"
                item["detail"] = str(error)
                raise TranslationIdEmbeddingError(
                    f"Unable to embed {item['translation_id']} ({item['stable_key']}): {error}"
                ) from error
            item["local_embed_status"] = status
            item["detail"] = ""
            results.append(self._result(item, status, ""))
        self._update_localized_titles()
        self.validate_all()
        return {
            "embedded": sum(result["status"] == "Inserted" for result in results),
            "already_present": sum(
                result["status"] == "Already Present" for result in results
            ),
            "skipped": sum(result["status"] == "Skipped by design" for result in results),
            "results": results,
        }

    def validate_all(self) -> None:
        """Require exactly one correct marker at every local embedding target."""
        for item in self.registry.items:
            if item.get("retired"):
                continue
            placement = item.get("placement", "")
            if placement in {
                "canvas_display_filename",
                "module_meta_audit",
                "module_item_audit",
                "registry_only",
            }:
                continue
            markers = self._target_markers(item)
            if markers != [item["translation_id"]]:
                raise TranslationIdEmbeddingError(
                    f"{item['translation_id']} validation found markers {markers or 'none'}."
                )

    def _embed_html_or_topic(self, item):
        paths = self._existing_paths(item)
        html_paths = [path for path in paths if path.suffix.lower() in {".html", ".htm"}]
        if html_paths:
            if len(html_paths) != 1:
                raise TranslationIdEmbeddingError(
                    f"Expected one visible HTML target, found {len(html_paths)}."
                )
            return self._append_html_marker(html_paths[0], item["translation_id"])
        xml_paths = [path for path in paths if path.suffix.lower() in {".xml", ".qti"}]
        targets = []
        for path in xml_paths:
            content = self._read_text(path)
            if re.search(r"<(?:text|message|description)(?:\s[^>]*)?>", content, re.IGNORECASE):
                targets.append(path)
        if len(targets) != 1:
            raise TranslationIdEmbeddingError(
                f"Expected one visible topic-text target, found {len(targets)}."
            )
        return self._append_xml_text_marker(
            targets[0], item["translation_id"], ("text", "message", "description")
        )

    def _embed_quiz_description(self, item):
        targets = [
            path
            for path in self._existing_paths(item)
            if path.name == "assessment_meta.xml"
        ]
        if len(targets) != 1:
            raise TranslationIdEmbeddingError(
                f"Expected one assessment_meta.xml target, found {len(targets)}."
            )
        return self._append_xml_text_marker(
            targets[0], item["translation_id"], ("description",)
        )

    def _embed_question_bank_title(self, item):
        targets = [
            path
            for path in self._existing_paths(item)
            if path.suffix.lower() in {".qti", ".xml"}
            and "<objectbank" in self._read_text(path).casefold()
        ]
        if len(targets) != 1:
            raise TranslationIdEmbeddingError(
                f"Expected one Question Bank QTI target, found {len(targets)}."
            )
        path = targets[0]
        content = self._read_text(path)
        pattern = re.compile(
            r"(<fieldlabel(?:\s[^>]*)?>\s*bank_title\s*</fieldlabel>\s*"
            r"<fieldentry(?:\s[^>]*)?>)(.*?)(</fieldentry>)",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(content)
        if not match:
            raise TranslationIdEmbeddingError("Question Bank has no bank_title field entry.")
        current = match.group(2)
        markers = self._markers(current)
        if markers == [item["translation_id"]]:
            return "Already Present"
        self._require_no_markers(markers, item["translation_id"])
        proposed = current.rstrip() + f" TranslationID: {item['translation_id']}"
        updated = content[: match.start(2)] + proposed + content[match.end(2) :]
        self._validate_xml(updated, path)
        self._write_text_atomic(path, updated)
        return "Inserted"

    def _embed_docx(self, item):
        targets = [path for path in self._existing_paths(item) if path.suffix.lower() == ".docx"]
        if len(targets) != 1:
            raise TranslationIdEmbeddingError(
                f"Expected one DOCX target, found {len(targets)}."
            )
        path = targets[0]
        try:
            with zipfile.ZipFile(path, "r") as source:
                document_xml = source.read("word/document.xml").decode("utf-8")
                markers = self._markers(document_xml)
                if markers == [item["translation_id"]]:
                    return "Already Present"
                self._require_no_markers(markers, item["translation_id"])
                paragraph = (
                    "<w:p><w:r><w:t>TranslationID: "
                    + item["translation_id"]
                    + "</w:t></w:r></w:p>"
                )
                section_match = re.search(r"<w:sectPr(?:\s|/|>)", document_xml)
                body_close = re.search(r"</w:body\s*>", document_xml)
                if section_match:
                    insertion = section_match.start()
                elif body_close:
                    insertion = body_close.start()
                else:
                    raise TranslationIdEmbeddingError("DOCX document.xml has no w:body end.")
                updated_xml = document_xml[:insertion] + paragraph + document_xml[insertion:]
                ET.fromstring(updated_xml.encode("utf-8"))
                archive_comment = source.comment
                archive_entries = [
                    (
                        info,
                        updated_xml.encode("utf-8")
                        if info.filename == "word/document.xml"
                        else source.read(info.filename),
                    )
                    for info in source.infolist()
                ]
        except (OSError, KeyError, UnicodeError, zipfile.BadZipFile, ET.ParseError) as error:
            raise TranslationIdEmbeddingError(f"Invalid DOCX package: {error}") from error
        self._rewrite_docx(path, archive_entries, archive_comment)
        return "Inserted"

    def _append_html_marker(self, path, translation_id):
        content = self._read_text(path)
        markers = self._markers(content)
        if markers == [translation_id]:
            return "Already Present"
        self._require_no_markers(markers, translation_id)
        marker = f"<p>TranslationID: {translation_id}</p>"
        match = re.search(r"</body\s*>", content, re.IGNORECASE)
        if not match:
            raise TranslationIdEmbeddingError(f"HTML target has no closing body: {path.name}")
        updated = content[: match.start()] + marker + content[match.start() :]
        soup = BeautifulSoup(updated, "html.parser")
        if not soup.body:
            raise TranslationIdEmbeddingError(f"HTML target is malformed: {path.name}")
        self._write_text_atomic(path, updated)
        return "Inserted"

    def _append_xml_text_marker(self, path, translation_id, element_names):
        content = self._read_text(path)
        element_pattern = "|".join(re.escape(name) for name in element_names)
        pattern = re.compile(
            rf"(<(?:{element_pattern})(?:\s[^>]*)?>)(.*?)(</(?:{element_pattern})>)",
            re.IGNORECASE | re.DOTALL,
        )
        matches = list(pattern.finditer(content))
        if not matches:
            raise TranslationIdEmbeddingError(
                f"XML target has no {'/'.join(element_names)} element: {path.name}"
            )
        # The first direct description/message/text is the visible Canvas body.
        match = matches[0]
        current = match.group(2)
        markers = self._markers(current)
        if markers == [translation_id]:
            return "Already Present"
        self._require_no_markers(markers, translation_id)
        marker = html.escape(f"<p>TranslationID: {translation_id}</p>")
        updated_value = current + marker
        updated = content[: match.start(2)] + updated_value + content[match.end(2) :]
        self._validate_xml(updated, path)
        self._write_text_atomic(path, updated)
        return "Inserted"

    def _target_markers(self, item):
        placement = item.get("placement", "")
        if placement == "question_bank_title":
            paths = [path for path in self._existing_paths(item) if path.suffix.lower() in {".xml", ".qti"}]
            values = []
            for path in paths:
                content = self._read_text(path)
                if "<objectbank" in content.casefold():
                    values.extend(self._markers(content))
            return values
        if placement == "docx_document_end_and_canvas_display_filename":
            paths = [path for path in self._existing_paths(item) if path.suffix.lower() == ".docx"]
            markers = []
            for path in paths:
                with zipfile.ZipFile(path, "r") as archive:
                    markers.extend(
                        self._markers(
                            archive.read("word/document.xml").decode("utf-8", errors="ignore")
                        )
                    )
            return markers
        if placement == "quiz_description":
            paths = [path for path in self._existing_paths(item) if path.name == "assessment_meta.xml"]
        else:
            paths = [
                path
                for path in self._existing_paths(item)
                if path.suffix.lower() in {".html", ".htm", ".xml", ".qti"}
            ]
            if any(path.suffix.lower() in {".html", ".htm"} for path in paths):
                paths = [path for path in paths if path.suffix.lower() in {".html", ".htm"}]
        markers = []
        for path in paths:
            markers.extend(self._markers(self._read_text(path)))
        return markers

    def _update_localized_titles(self):
        if not self.language:
            return
        for item in self.registry.items:
            if item.get("retired"):
                continue
            title = self._localized_title(item)
            instance = item["instances"][self.language]
            if title:
                instance["title"] = title
            if self.target_course_id:
                instance["course_id"] = self.target_course_id
            instance["presence"] = "not_checked"
            instance["id_status"] = "not_checked"

    def _localized_title(self, item):
        module_title = self._module_meta_title(item)
        if module_title:
            return module_title
        item_type = item.get("item_type")
        paths = self._existing_paths(item)
        if item_type == "Question Bank":
            for path in paths:
                if path.suffix.lower() not in {".xml", ".qti"}:
                    continue
                content = self._read_text(path)
                match = re.search(
                    r"<fieldlabel(?:\s[^>]*)?>\s*bank_title\s*</fieldlabel>\s*"
                    r"<fieldentry(?:\s[^>]*)?>(.*?)</fieldentry>",
                    content,
                    re.IGNORECASE | re.DOTALL,
                )
                if match:
                    return VISIBLE_MARKER_RE.sub("", html.unescape(match.group(1))).strip()
        preferred_names = {
            "Quiz": ("assessment_meta.xml",),
            "Assignment": ("assignment_settings.xml",),
            "Discussion": ("topic_meta.xml", "assignment_settings.xml"),
            "Announcement": ("topic_meta.xml", "assignment_settings.xml"),
        }.get(item_type, ())
        ordered_paths = sorted(
            paths,
            key=lambda path: (
                preferred_names.index(path.name) if path.name in preferred_names else len(preferred_names),
                path.as_posix().casefold(),
            ),
        )
        for path in ordered_paths:
            if path.suffix.lower() not in {".html", ".htm", ".xml", ".qti"}:
                continue
            content = self._read_text(path)
            soup = BeautifulSoup(
                content,
                "xml" if path.suffix.lower() in {".xml", ".qti"} else "html.parser",
            )
            title = soup.find("title")
            if title and title.get_text(strip=True):
                return VISIBLE_MARKER_RE.sub("", title.get_text(" ", strip=True)).strip()
        return str(item.get("source_title", ""))

    def _module_meta_title(self, item):
        module_path = self.course_root / "course_settings" / "module_meta.xml"
        if not module_path.is_file():
            return ""
        soup = BeautifulSoup(self._read_text(module_path), "xml")
        module_item_identifier = item.get("module_item_identifier")
        module_identifier = item.get("module_identifier")
        manifest_identifier = item.get("manifest_identifier")
        if item.get("item_type") == "Module" and module_identifier:
            tag = soup.find("module", attrs={"identifier": module_identifier})
            title = tag.find("title", recursive=False) if tag else None
            return title.get_text(" ", strip=True) if title else ""
        if module_item_identifier:
            tag = soup.find("item", attrs={"identifier": module_item_identifier})
            title = tag.find("title", recursive=False) if tag else None
            return title.get_text(" ", strip=True) if title else ""
        if manifest_identifier:
            for tag in soup.find_all("item"):
                identifierref = tag.find("identifierref", recursive=False)
                if identifierref and identifierref.get_text(strip=True) == manifest_identifier:
                    title = tag.find("title", recursive=False)
                    if title:
                        return title.get_text(" ", strip=True)
        return ""

    def _existing_paths(self, item):
        paths = []
        for relative in item.get("package_paths", []):
            path = (self.course_root / Path(relative)).resolve()
            try:
                path.relative_to(self.course_root)
            except ValueError as error:
                raise TranslationIdEmbeddingError(
                    f"Registry path escapes the IMSCC workspace: {relative}"
                ) from error
            if path.is_file():
                paths.append(path)
        if not paths and item.get("placement") not in {
            "registry_only",
            "module_meta_audit",
            "module_item_audit",
            "canvas_display_filename",
        }:
            raise TranslationIdEmbeddingError("No registered package target exists.")
        return paths

    @staticmethod
    def _markers(content):
        return [value.upper() for value in VISIBLE_MARKER_RE.findall(str(content))]

    @staticmethod
    def _require_no_markers(markers, expected):
        if not markers:
            return
        if len(markers) > 1:
            raise TranslationIdEmbeddingError(
                f"Multiple Translation ID markers found: {', '.join(markers)}"
            )
        raise TranslationIdEmbeddingError(
            f"Different Translation ID marker found: {markers[0]} (expected {expected})."
        )

    @staticmethod
    def _read_text(path):
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise TranslationIdEmbeddingError(f"Unable to read {path}: {error}") from error

    @staticmethod
    def _validate_xml(content, path):
        try:
            ET.fromstring(content.encode("utf-8"))
        except ET.ParseError as error:
            raise TranslationIdEmbeddingError(
                f"Embedding produced malformed XML in {path.name}: {error}"
            ) from error

    @staticmethod
    def _write_text_atomic(path, content):
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temp_name = output.name
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_name, path)
        except OSError as error:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise TranslationIdEmbeddingError(f"Unable to save {path}: {error}") from error

    @staticmethod
    def _rewrite_docx(path, archive_entries, archive_comment):
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temp_name = output.name
            with zipfile.ZipFile(temp_name, "w") as target:
                target.comment = archive_comment
                for info, content in archive_entries:
                    target.writestr(info, content)
            os.replace(temp_name, path)
        except OSError as error:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise TranslationIdEmbeddingError(f"Unable to rebuild DOCX {path}: {error}") from error

    @staticmethod
    def _result(item, status, detail):
        return {
            "translation_id": item["translation_id"],
            "item_type": item["item_type"],
            "status": status,
            "detail": detail,
            "package_paths": list(item.get("package_paths", [])),
        }

    @staticmethod
    def _coerce_registry(registry):
        try:
            if isinstance(registry, TranslationIdRegistry):
                return registry
            if isinstance(registry, Mapping):
                return TranslationIdRegistry.from_dict(registry)
            return TranslationIdRegistry.load(registry)
        except TranslationIdRegistryError as error:
            raise TranslationIdEmbeddingError(str(error)) from error

