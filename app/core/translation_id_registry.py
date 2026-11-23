"""Stable, language-neutral Translation ID registry for Canvas IMSCC packages.

The registry deliberately inventories package objects independently from the
Gemini translation list.  It is safe to build before translation because this
module only reads the IMSCC workspace and writes a sidecar JSON registry.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from bs4 import BeautifulSoup


SCHEMA_VERSION = 2
LANGUAGES = ("EN", "PTBR", "SPA", "FRA")
TYPE_CODES = {
    "Announcement": "AN",
    "Assignment": "AS",
    "Assignment Group": "AG",
    "Course Metadata": "CM",
    "Course Settings": "CS",
    "Discussion": "DI",
    "External Tool": "ET",
    "External URL": "EU",
    "File": "FI",
    "File Metadata": "FM",
    "Grading Standard": "GS",
    "Media Metadata": "MM",
    "Module": "MO",
    "Module Header": "MO",
    "Package Manifest": "PM",
    "Page": "PG",
    "Question Bank": "QB",
    "Quiz": "QZ",
    "Rubric": "RU",
    "Syllabus": "SY",
}

VISIBLE_MARKER_RE = re.compile(
    r"TranslationID:\s*([A-Z0-9]+-[A-Z]{2}-\d{3})",
    re.IGNORECASE,
)
FILENAME_MARKER_RE = re.compile(
    r"\[([A-Z0-9]+-FI-\d{3})\]",
    re.IGNORECASE,
)
FULL_ID_RE = re.compile(r"^([A-Z0-9]+)-([A-Z]{2})-(\d{3})$")
COURSE_CODE_RE = re.compile(r"^[A-Z0-9]+$")


class TranslationIdRegistryError(ValueError):
    """Raised when inventory or registry data would make IDs unsafe."""


def normalize_course_code(value: str) -> str:
    """Return a validated canonical course code."""
    normalized = re.sub(r"[\s_-]+", "", str(value or "").upper())
    if not normalized or not COURSE_CODE_RE.fullmatch(normalized):
        raise TranslationIdRegistryError(
            "Translation ID course code must contain only uppercase letters and numbers."
        )
    return normalized


def empty_language_instance(language: str) -> Dict[str, Any]:
    source = language == "EN"
    return {
        "course_id": None,
        "content_id": None,
        "module_item_id": None,
        "title": None,
        "url": None,
        "presence": "pending" if source else "not_translated",
        "id_status": "pending" if source else "not_checked",
    }


class TranslationIdRegistry:
    """Validated registry data plus atomic persistence helpers."""

    def __init__(
        self,
        course_code: str,
        source_course_id: Optional[str],
        items: Sequence[Mapping[str, Any]],
        languages: Sequence[str] = LANGUAGES,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        if int(schema_version) != SCHEMA_VERSION:
            raise TranslationIdRegistryError(
                f"Unsupported Translation ID registry schema: {schema_version}"
            )
        self.schema_version = SCHEMA_VERSION
        self.course_code = normalize_course_code(course_code)
        self.source_course_id = (
            str(source_course_id).strip() if source_course_id is not None else None
        )
        self.languages = list(languages)
        if self.languages != list(LANGUAGES):
            raise TranslationIdRegistryError(
                "Registry languages must be EN, PTBR, SPA, and FRA in that order."
            )
        self.items = [deepcopy(dict(item)) for item in items]
        self._validate()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationIdRegistry":
        return cls(
            course_code=data.get("course_code", ""),
            source_course_id=data.get("source_course_id"),
            items=data.get("items", []),
            languages=data.get("languages", LANGUAGES),
            schema_version=data.get("schema_version", 0),
        )

    @classmethod
    def load(cls, path: os.PathLike[str] | str) -> "TranslationIdRegistry":
        try:
            with open(path, "r", encoding="utf-8") as registry_file:
                return cls.from_dict(json.load(registry_file))
        except (OSError, json.JSONDecodeError) as error:
            raise TranslationIdRegistryError(
                f"Unable to load Translation ID registry {path}: {error}"
            ) from error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "course_code": self.course_code,
            "source_course_id": self.source_course_id,
            "languages": list(self.languages),
            "items": deepcopy(self.items),
        }

    def save(self, path: os.PathLike[str] | str) -> str:
        """Atomically persist the registry and return its absolute path."""
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                json.dump(self.to_dict(), temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, target)
        except OSError as error:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise TranslationIdRegistryError(
                f"Unable to save Translation ID registry {target}: {error}"
            ) from error
        return str(target)

    def update_instance(
        self, translation_id: str, language: str, **values: Any
    ) -> Dict[str, Any]:
        """Update exactly one language instance without replacing its siblings."""
        language = str(language).upper()
        if language not in LANGUAGES:
            raise TranslationIdRegistryError(f"Unsupported registry language: {language}")
        item = next(
            (entry for entry in self.items if entry["translation_id"] == translation_id),
            None,
        )
        if item is None:
            raise TranslationIdRegistryError(
                f"Unknown Translation ID: {translation_id}"
            )
        allowed = set(empty_language_instance(language))
        unexpected = set(values) - allowed
        if unexpected:
            raise TranslationIdRegistryError(
                "Unsupported language-instance fields: " + ", ".join(sorted(unexpected))
            )
        item["instances"][language].update(values)
        return deepcopy(item["instances"][language])

    def _validate(self) -> None:
        translation_ids: Dict[str, str] = {}
        stable_keys: Dict[str, str] = {}
        for item in self.items:
            translation_id = str(item.get("translation_id", "")).upper()
            short_id = str(item.get("short_id", "")).upper()
            stable_key = str(item.get("stable_key", "")).strip()
            item_type = str(item.get("item_type", ""))
            match = FULL_ID_RE.fullmatch(translation_id)
            if not match or match.group(1) != self.course_code:
                raise TranslationIdRegistryError(
                    f"Malformed or wrong-course Translation ID: {translation_id}"
                )
            expected_code = TYPE_CODES.get(item_type)
            if not expected_code or match.group(2) != expected_code:
                raise TranslationIdRegistryError(
                    f"Translation ID {translation_id} does not match item type {item_type}."
                )
            if short_id != f"{match.group(2)}-{match.group(3)}":
                raise TranslationIdRegistryError(
                    f"Short ID does not match {translation_id}: {short_id}"
                )
            if not stable_key:
                raise TranslationIdRegistryError(
                    f"Translation ID {translation_id} has no stable key."
                )
            if translation_id in translation_ids:
                raise TranslationIdRegistryError(
                    f"Duplicate Translation ID {translation_id} for {stable_key} and "
                    f"{translation_ids[translation_id]}."
                )
            if stable_key in stable_keys:
                raise TranslationIdRegistryError(
                    f"Stable key {stable_key} maps to both {translation_id} and "
                    f"{stable_keys[stable_key]}."
                )
            translation_ids[translation_id] = stable_key
            stable_keys[stable_key] = translation_id
            instances = item.get("instances")
            if not isinstance(instances, dict) or set(instances) != set(LANGUAGES):
                raise TranslationIdRegistryError(
                    f"Translation ID {translation_id} must contain all four language instances."
                )


class TranslationIdRegistryBuilder:
    """Build or reconcile a complete logical-item inventory from an IMSCC tree."""

    def __init__(
        self,
        course_root: os.PathLike[str] | str,
        course_code: str,
        source_course_id: Optional[str] = None,
        existing_registry: Optional[
            TranslationIdRegistry | Mapping[str, Any] | os.PathLike[str] | str
        ] = None,
    ) -> None:
        self.course_root = Path(course_root).resolve()
        self.course_code = normalize_course_code(course_code)
        self.source_course_id = (
            str(source_course_id).strip() if source_course_id is not None else None
        )
        if not self.course_root.is_dir():
            raise TranslationIdRegistryError(
                f"IMSCC workspace does not exist: {self.course_root}"
            )
        self.existing_registry = self._coerce_registry(existing_registry)
        if self.existing_registry and self.existing_registry.course_code != self.course_code:
            raise TranslationIdRegistryError(
                "The existing registry belongs to course "
                f"{self.existing_registry.course_code}, not {self.course_code}."
            )
        if (
            self.existing_registry
            and self.source_course_id
            and self.existing_registry.source_course_id
            and self.existing_registry.source_course_id != self.source_course_id
        ):
            raise TranslationIdRegistryError(
                "The existing registry belongs to English Canvas course "
                f"{self.existing_registry.source_course_id}, not {self.source_course_id}."
            )

    def build(self) -> TranslationIdRegistry:
        candidates = self._inventory_candidates()
        existing_by_key = {
            item["stable_key"]: deepcopy(item)
            for item in (self.existing_registry.items if self.existing_registry else [])
        }
        reserved_by_code: Dict[str, set[int]] = {code: set() for code in TYPE_CODES.values()}
        for item in existing_by_key.values():
            match = FULL_ID_RE.fullmatch(str(item.get("translation_id", "")))
            if match:
                reserved_by_code.setdefault(match.group(2), set()).add(int(match.group(3)))

        items: List[Dict[str, Any]] = []
        current_keys = set()
        marker_owners: Dict[str, str] = {}
        for candidate in candidates:
            stable_key = candidate["stable_key"]
            current_keys.add(stable_key)
            existing = existing_by_key.get(stable_key)
            markers = self._markers_for_paths(candidate["package_paths"])
            if len(markers) > 1:
                raise TranslationIdRegistryError(
                    f"Logical item {stable_key} contains conflicting Translation IDs: "
                    + ", ".join(sorted(markers))
                )

            marker = next(iter(markers), None)
            if marker:
                self._validate_marker(marker, candidate["item_type"], stable_key)
                previous_owner = marker_owners.get(marker)
                if previous_owner and previous_owner != stable_key:
                    raise TranslationIdRegistryError(
                        f"Translation ID {marker} appears on both {previous_owner} and {stable_key}."
                    )
                marker_owners[marker] = stable_key

            if existing:
                translation_id = existing["translation_id"]
                canonical_source_title = existing.get("source_title")
                if marker and marker != translation_id:
                    raise TranslationIdRegistryError(
                        f"Logical item {stable_key} is registered as {translation_id} but "
                        f"contains {marker}."
                    )
                item = existing
                item.update(candidate)
                item["source_title"] = canonical_source_title or candidate["source_title"]
                item["translation_id"] = translation_id
                item["short_id"] = translation_id.split("-", 1)[1]
                item["retired"] = False
                item["instances"]["EN"]["title"] = item["source_title"]
                if self.source_course_id:
                    item["instances"]["EN"]["course_id"] = self.source_course_id
            elif marker:
                item = self._new_item(candidate, marker)
                reserved_by_code[TYPE_CODES[candidate["item_type"]]].add(
                    int(marker.rsplit("-", 1)[1])
                )
            else:
                code = TYPE_CODES[candidate["item_type"]]
                sequence = self._next_sequence(reserved_by_code[code])
                reserved_by_code[code].add(sequence)
                item = self._new_item(
                    candidate, f"{self.course_code}-{code}-{sequence:03d}"
                )
            items.append(item)

        # Keep retired records so their IDs can never be reused and later
        # language audits retain their historical identity.
        for stable_key, existing in existing_by_key.items():
            if stable_key in current_keys:
                continue
            retired = deepcopy(existing)
            retired["retired"] = True
            retired["instances"]["EN"]["presence"] = "missing"
            retired["instances"]["EN"]["id_status"] = "not_checked"
            items.append(retired)

        items.sort(key=self._item_sort_key)
        registry = TranslationIdRegistry(
            course_code=self.course_code,
            source_course_id=self.source_course_id
            or (self.existing_registry.source_course_id if self.existing_registry else None),
            items=items,
        )
        return registry

    def _inventory_candidates(self) -> List[Dict[str, Any]]:
        manifest_path = self.course_root / "imsmanifest.xml"
        if not manifest_path.is_file():
            raise TranslationIdRegistryError(
                f"IMSCC workspace is missing {manifest_path.name}."
            )
        manifest = self._read_xml(manifest_path)
        candidates: Dict[str, Dict[str, Any]] = {}
        consumed_paths = {"imsmanifest.xml"}

        self._add_candidate(
            candidates,
            "Package Manifest",
            f"manifest:{manifest.find('manifest').get('identifier', 'imsmanifest.xml')}",
            "IMS Common Cartridge Manifest",
            ["imsmanifest.xml"],
            "registry_only",
        )

        module_titles, module_identifierrefs = self._inventory_modules(candidates)
        files_meta_names = self._files_meta_names()

        resources = manifest.find_all("resource")
        assessment_ids = {
            resource.get("identifier", "")
            for resource in resources
            if "assessment" in str(resource.get("type", "")).lower()
            and "associatedcontent" not in str(resource.get("type", "")).lower()
        }
        for resource in sorted(resources, key=lambda value: value.get("identifier", "")):
            identifier = str(resource.get("identifier", "")).strip()
            resource_type = str(resource.get("type", "")).lower()
            href = self._normalize_relpath(resource.get("href", ""))
            paths = self._resource_paths(resource)
            intended_use = str(resource.get("intendeduse", "")).lower()

            # Metadata companions and duplicate non-CC quiz wrappers belong to
            # their owning logical item rather than receiving another ID.
            if "associatedcontent" in resource_type:
                parent = PurePosixPath(href).parent.as_posix() if href else ""
                if parent in assessment_ids or PurePosixPath(href).stem in assessment_ids:
                    continue

            item_type = None
            placement = "registry_only"
            title = module_titles.get(identifier, "")

            if intended_use == "syllabus" or href == "course_settings/syllabus.html":
                item_type = "Syllabus"
                placement = "html_body_end"
                title = title or "Course Syllabus"
            elif "assessment" in resource_type and "associatedcontent" not in resource_type:
                item_type = "Quiz"
                placement = "quiz_description"
                paths = self._assessment_paths(identifier, paths)
                title = title or self._title_from_paths(paths)
            elif href.startswith("wiki_content/"):
                item_type = "Page"
                placement = "html_body_end"
                title = title or self._title_from_paths(paths)
            elif self._paths_contain(paths, "assignment_settings.xml"):
                title = title or self._title_from_paths(paths)
                item_type = self._assignment_kind(paths, title)
                placement = {
                    "Assignment": "assignment_html_body_end",
                    "Discussion": "discussion_visible_text_end",
                    "Announcement": "announcement_visible_text_end",
                }[item_type]
            elif self._paths_have_objectbank(paths):
                item_type = "Question Bank"
                placement = "question_bank_title"
                title = self._bank_title(paths) or title
            elif resource_type.startswith("imsdt_"):
                item_type = "Discussion"
                placement = "discussion_visible_text_end"
                title = title or self._title_from_paths(paths)
            elif href.startswith("web_resources/") and href:
                item_type = "File"
                placement = (
                    "docx_document_end_and_canvas_display_filename"
                    if PurePosixPath(href).suffix.lower() == ".docx"
                    else "canvas_display_filename"
                )
                title = files_meta_names.get(identifier) or PurePosixPath(href).name
            elif resource_type == "webcontent" and href:
                item_type = "File"
                placement = (
                    "docx_document_end_and_canvas_display_filename"
                    if PurePosixPath(href).suffix.lower() == ".docx"
                    else "canvas_display_filename"
                )
                title = files_meta_names.get(identifier) or PurePosixPath(href).name
            elif resource_type.startswith("imswl_"):
                # Canvas duplicates external URL/tool launch metadata in IMSCC
                # resources whose identifiers do not reliably match the module
                # item identifierref.  module_meta.xml is the authoritative
                # logical inventory and prevents a second audit row here.
                continue

            if not item_type:
                continue
            if not paths and href:
                paths = [href]
            consumed_paths.update(paths)
            self._add_candidate(
                candidates,
                item_type,
                f"manifest:{identifier}" if identifier else f"path:{href}",
                title or PurePosixPath(href).name or identifier,
                paths,
                placement,
                manifest_identifier=identifier or None,
            )

        self._inventory_question_banks(candidates, consumed_paths)
        self._inventory_structured_metadata(candidates, consumed_paths)
        self._inventory_unclaimed_files(candidates, consumed_paths, files_meta_names)
        return sorted(candidates.values(), key=self._candidate_sort_key)

    def _inventory_modules(self, candidates: Dict[str, Dict[str, Any]]):
        module_path = self.course_root / "course_settings" / "module_meta.xml"
        titles: Dict[str, str] = {}
        identifierrefs = set()
        if not module_path.is_file():
            return titles, identifierrefs
        soup = self._read_xml(module_path)
        relpath = "course_settings/module_meta.xml"
        for module in soup.find_all("module"):
            identifier = str(module.get("identifier", "")).strip()
            title = self._direct_child_text(module, "title") or identifier
            self._add_candidate(
                candidates,
                "Module",
                f"module:{identifier}",
                title,
                [relpath],
                "module_meta_audit",
                module_identifier=identifier,
            )
            items_tag = module.find("items", recursive=False)
            if not items_tag:
                continue
            for item in items_tag.find_all("item", recursive=False):
                item_identifier = str(item.get("identifier", "")).strip()
                content_type = self._direct_child_text(item, "content_type")
                item_title = self._direct_child_text(item, "title") or item_identifier
                identifierref = self._direct_child_text(item, "identifierref")
                if identifierref:
                    identifierrefs.add(identifierref)
                    titles.setdefault(identifierref, item_title)
                if content_type == "ContextModuleSubHeader":
                    self._add_candidate(
                        candidates,
                        "Module Header",
                        f"module-item:{item_identifier}",
                        item_title,
                        [relpath],
                        "module_meta_audit",
                        module_identifier=identifier,
                        module_item_identifier=item_identifier,
                    )
                elif content_type == "ExternalUrl":
                    self._add_candidate(
                        candidates,
                        "External URL",
                        f"module-item:{item_identifier}",
                        item_title,
                        [relpath],
                        "module_item_audit",
                        module_identifier=identifier,
                        module_item_identifier=item_identifier,
                        external_url=self._direct_child_text(item, "url") or None,
                    )
                elif "ExternalTool" in content_type or content_type == "Lti::ToolProxy":
                    self._add_candidate(
                        candidates,
                        "External Tool",
                        f"module-item:{item_identifier}",
                        item_title,
                        [relpath],
                        "module_item_audit",
                        module_identifier=identifier,
                        module_item_identifier=item_identifier,
                        manifest_identifier=identifierref or None,
                    )
        return titles, identifierrefs

    def _inventory_question_banks(
        self, candidates: Dict[str, Dict[str, Any]], consumed_paths: set[str]
    ) -> None:
        qti_paths = sorted(
            list(self.course_root.rglob("*.qti")),
            key=lambda path: self._relative(path).casefold(),
        )
        for qti_path in qti_paths:
            relpath = self._relative(qti_path)
            if relpath in consumed_paths:
                continue
            try:
                soup = self._read_xml(qti_path)
            except TranslationIdRegistryError:
                continue
            for bank in soup.find_all("objectbank"):
                identifier = str(bank.get("ident", "")).strip()
                if not identifier:
                    identifier = PurePosixPath(relpath).stem
                title = self._bank_title([relpath]) or identifier
                self._add_candidate(
                    candidates,
                    "Question Bank",
                    f"qti-objectbank:{identifier}",
                    title,
                    [relpath],
                    "question_bank_title",
                    qti_objectbank_identifier=identifier,
                )
                consumed_paths.add(relpath)

    def _inventory_structured_metadata(
        self, candidates: Dict[str, Dict[str, Any]], consumed_paths: set[str]
    ) -> None:
        specs = (
            ("course_settings/assignment_groups.xml", "assignmentGroup", "Assignment Group", "assignment-group"),
            ("course_settings/grading_standards.xml", "gradingStandard", "Grading Standard", "grading-standard"),
            ("course_settings/rubrics.xml", "rubric", "Rubric", "rubric"),
        )
        for relpath, tag_name, item_type, prefix in specs:
            path = self.course_root / Path(relpath)
            if not path.is_file():
                continue
            soup = self._read_xml(path)
            for index, element in enumerate(soup.find_all(tag_name), 1):
                identifier = str(element.get("identifier", "")).strip() or str(index)
                title = self._direct_child_text(element, "title") or f"{item_type} {index}"
                self._add_candidate(
                    candidates,
                    item_type,
                    f"{prefix}:{identifier}",
                    title,
                    [relpath],
                    "registry_only",
                )
            consumed_paths.add(relpath)

        singleton_specs = (
            ("course_settings/context.xml", "Course Metadata", "Canvas Course Metadata", "course-metadata"),
            ("course_settings/course_settings.xml", "Course Settings", "Canvas Course Settings", "course-settings"),
            ("course_settings/files_meta.xml", "File Metadata", "Canvas File Metadata", "file-metadata"),
            ("course_settings/media_tracks.xml", "Media Metadata", "Canvas Media Metadata", "media-metadata"),
        )
        for relpath, item_type, title, stable_name in singleton_specs:
            if not (self.course_root / Path(relpath)).is_file():
                continue
            self._add_candidate(
                candidates,
                item_type,
                f"metadata:{stable_name}",
                title,
                [relpath],
                "registry_only",
            )
            consumed_paths.add(relpath)

    def _inventory_unclaimed_files(
        self,
        candidates: Dict[str, Dict[str, Any]],
        consumed_paths: set[str],
        files_meta_names: Mapping[str, str],
    ) -> None:
        excluded_prefixes = ("course_settings/", "non_cc_assessments/", "wiki_content/")
        excluded_names = {"imsmanifest.xml", "assessment_meta.xml", "assessment_qti.xml", "assignment_settings.xml"}
        known_names = {value.casefold(): value for value in files_meta_names.values() if value}
        for path in sorted(
            (value for value in self.course_root.rglob("*") if value.is_file()),
            key=lambda value: self._relative(value).casefold(),
        ):
            relpath = self._relative(path)
            if relpath in consumed_paths:
                continue
            posix = PurePosixPath(relpath)
            if relpath.startswith(excluded_prefixes) or posix.name in excluded_names:
                continue
            if posix.suffix.lower() in {".xml", ".qti", ".html", ".htm"} and not relpath.startswith("web_resources/"):
                continue
            title = known_names.get(posix.name.casefold(), posix.name)
            self._add_candidate(
                candidates,
                "File",
                f"path:{relpath}",
                title,
                [relpath],
                "docx_document_end_and_canvas_display_filename"
                if posix.suffix.lower() == ".docx"
                else "canvas_display_filename",
            )

    def _files_meta_names(self) -> Dict[str, str]:
        path = self.course_root / "course_settings" / "files_meta.xml"
        if not path.is_file():
            return {}
        soup = self._read_xml(path)
        names = {}
        for file_tag in soup.find_all("file"):
            identifier = str(file_tag.get("identifier", "")).strip()
            display_name = self._direct_child_text(file_tag, "display_name")
            if identifier and display_name:
                names[identifier] = display_name
        return names

    def _assessment_paths(self, identifier: str, paths: Sequence[str]) -> List[str]:
        collected = set(paths)
        assessment_dir = self.course_root / identifier
        if assessment_dir.is_dir():
            for path in assessment_dir.rglob("*"):
                if path.is_file():
                    collected.add(self._relative(path))
        duplicate = self.course_root / "non_cc_assessments" / f"{identifier}.xml.qti"
        if duplicate.is_file():
            collected.add(self._relative(duplicate))
        return sorted(collected, key=str.casefold)

    def _assignment_kind(self, paths: Sequence[str], title: str) -> str:
        haystack = " ".join([title, *paths]).casefold()
        if "announcement" in haystack:
            return "Announcement"
        if "discussion" in haystack:
            return "Discussion"
        for relpath in paths:
            if not relpath.lower().endswith(".xml"):
                continue
            try:
                content = (self.course_root / Path(relpath)).read_text(
                    encoding="utf-8-sig", errors="ignore"
                )
            except OSError:
                continue
            lowered = content.casefold()
            if "<is_announcement>true" in lowered or "<announcement>true" in lowered:
                return "Announcement"
            if "<discussion_topic" in lowered or "<topicmeta" in lowered:
                return "Discussion"
        return "Assignment"

    def _resource_paths(self, resource) -> List[str]:
        paths = []
        href = self._normalize_relpath(resource.get("href", ""))
        if href:
            paths.append(href)
        for file_tag in resource.find_all("file"):
            file_href = self._normalize_relpath(file_tag.get("href", ""))
            if file_href:
                paths.append(file_href)
        return sorted(set(paths), key=str.casefold)

    def _title_from_paths(self, paths: Sequence[str]) -> str:
        preferred = sorted(
            paths,
            key=lambda value: (
                0 if value.endswith("assessment_meta.xml") else 1,
                0 if value.endswith("assignment_settings.xml") else 1,
                value.casefold(),
            ),
        )
        for relpath in preferred:
            path = self.course_root / Path(relpath)
            if not path.is_file() or path.suffix.lower() not in {".xml", ".qti", ".html", ".htm"}:
                continue
            try:
                content = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            parser = "xml" if path.suffix.lower() in {".xml", ".qti"} else "html.parser"
            soup = BeautifulSoup(content, parser)
            title = soup.find("title")
            if title and title.get_text(strip=True):
                return title.get_text(" ", strip=True)
        return ""

    def _bank_title(self, paths: Sequence[str]) -> str:
        for relpath in paths:
            path = self.course_root / Path(relpath)
            if not path.is_file() or path.suffix.lower() not in {".xml", ".qti"}:
                continue
            try:
                soup = self._read_xml(path)
            except TranslationIdRegistryError:
                continue
            for field in soup.find_all(("qtimetadatafield", "field")):
                label = field.find("fieldlabel")
                entry = field.find("fieldentry")
                if label and entry and label.get_text(strip=True) == "bank_title":
                    return entry.get_text(" ", strip=True)
        return ""

    def _paths_have_objectbank(self, paths: Sequence[str]) -> bool:
        for relpath in paths:
            path = self.course_root / Path(relpath)
            if not path.is_file() or path.suffix.lower() not in {".xml", ".qti"}:
                continue
            try:
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as source:
                    if "<objectbank" in source.read(131072).lower():
                        return True
            except OSError:
                continue
        return False

    @staticmethod
    def _paths_contain(paths: Sequence[str], basename: str) -> bool:
        return any(PurePosixPath(path).name == basename for path in paths)

    def _markers_for_paths(self, paths: Sequence[str]) -> set[str]:
        markers = set()
        for relpath in paths:
            markers.update(match.upper() for match in FILENAME_MARKER_RE.findall(relpath))
            path = self.course_root / Path(relpath)
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            try:
                if suffix == ".docx":
                    with zipfile.ZipFile(path) as archive:
                        content = archive.read("word/document.xml").decode(
                            "utf-8", errors="ignore"
                        )
                elif suffix in {".html", ".htm", ".xml", ".qti", ".txt"}:
                    content = path.read_text(encoding="utf-8-sig", errors="ignore")
                else:
                    continue
            except (OSError, KeyError, zipfile.BadZipFile):
                continue
            markers.update(match.upper() for match in VISIBLE_MARKER_RE.findall(content))
        return markers

    def _validate_marker(self, marker: str, item_type: str, stable_key: str) -> None:
        match = FULL_ID_RE.fullmatch(marker)
        expected_code = TYPE_CODES[item_type]
        if not match or match.group(1) != self.course_code:
            raise TranslationIdRegistryError(
                f"Logical item {stable_key} contains a malformed or wrong-course ID: {marker}."
            )
        if match.group(2) != expected_code:
            raise TranslationIdRegistryError(
                f"Logical item {stable_key} is {item_type} but contains {marker}."
            )

    def _new_item(self, candidate: Mapping[str, Any], translation_id: str) -> Dict[str, Any]:
        instances = {language: empty_language_instance(language) for language in LANGUAGES}
        instances["EN"]["course_id"] = self.source_course_id
        instances["EN"]["title"] = candidate["source_title"]
        item = deepcopy(dict(candidate))
        item.update(
            {
                "translation_id": translation_id,
                "short_id": translation_id.split("-", 1)[1],
                "retired": False,
                "instances": instances,
            }
        )
        return item

    @staticmethod
    def _next_sequence(reserved: set[int]) -> int:
        sequence = max(reserved, default=0) + 1
        if sequence > 999:
            raise TranslationIdRegistryError(
                "Translation ID sequence exhausted the three-digit range."
            )
        return sequence

    @staticmethod
    def _coerce_registry(existing):
        if existing is None:
            return None
        if isinstance(existing, TranslationIdRegistry):
            return existing
        if isinstance(existing, Mapping):
            return TranslationIdRegistry.from_dict(existing)
        return TranslationIdRegistry.load(existing)

    @staticmethod
    def _candidate_sort_key(item: Mapping[str, Any]):
        return (
            TYPE_CODES[item["item_type"]],
            str(item["stable_key"]).casefold(),
            str(item["source_title"]).casefold(),
        )

    @staticmethod
    def _item_sort_key(item: Mapping[str, Any]):
        match = FULL_ID_RE.fullmatch(str(item["translation_id"]))
        return (match.group(2), int(match.group(3))) if match else ("ZZ", 9999)

    @staticmethod
    def _direct_child_text(element, name: str) -> str:
        child = element.find(name, recursive=False)
        return child.get_text(" ", strip=True) if child else ""

    @staticmethod
    def _normalize_relpath(value: Any) -> str:
        normalized = str(value or "").replace("\\", "/").lstrip("/")
        parts = [part for part in normalized.split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            raise TranslationIdRegistryError(
                f"IMSCC resource path escapes the package root: {value}"
            )
        return "/".join(parts)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.course_root).as_posix()

    @staticmethod
    def _read_xml(path: Path):
        try:
            content = path.read_text(encoding="utf-8-sig", errors="strict")
        except (OSError, UnicodeError) as error:
            raise TranslationIdRegistryError(f"Unable to read XML {path}: {error}") from error
        soup = BeautifulSoup(content, "xml")
        if not soup.find():
            raise TranslationIdRegistryError(f"Unable to parse XML {path}.")
        return soup

    @staticmethod
    def _add_candidate(
        candidates: Dict[str, Dict[str, Any]],
        item_type: str,
        stable_key: str,
        source_title: str,
        package_paths: Iterable[str],
        placement: str,
        **extra: Any,
    ) -> None:
        paths = sorted({str(path).replace("\\", "/") for path in package_paths if path}, key=str.casefold)
        candidate = {
            "item_type": item_type,
            "source_title": str(source_title or stable_key).strip(),
            "stable_key": str(stable_key).strip(),
            "package_paths": paths,
            "placement": placement,
        }
        candidate.update({key: value for key, value in extra.items() if value is not None})
        existing = candidates.get(stable_key)
        if existing and existing != candidate:
            raise TranslationIdRegistryError(
                f"Stable key {stable_key} describes more than one logical item."
            )
        candidates[stable_key] = candidate

