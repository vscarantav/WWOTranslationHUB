"""Glossary layers used only by the Canvas CSE-course translation flow."""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.language_config import normalize_language_code


class CSEGlossaryLayer:
    """A single independently searched glossary level."""

    ENGLISH_HEADERS = {"english", "english term"}
    CONTEXT_HEADERS = {"context", "usage context", "notes"}
    TRANSLATION_HEADERS = {
        "PTBR": {
            "portuguese",
            "portuguese (brazil)",
            "portuguese translation",
            "português",
            "português (brasil)",
            "pt-br translation",
            "ptbr translation",
        },
        "SPA": {
            "spanish",
            "spanish translation",
            "español",
            "spa translation",
            "es translation",
        },
        "FRA": {
            "french",
            "french translation",
            "français",
            "fra translation",
            "fr translation",
        },
    }

    def __init__(self, name, priority, source_path, entries, target_language):
        self.name = str(name)
        self.priority = int(priority)
        self.source_path = str(source_path)
        self.entries = [dict(entry) for entry in entries]
        self.target_language = normalize_language_code(target_language)

    @staticmethod
    def _clean_cell(value):
        return re.sub(r"\*\*", "", str(value or "")).strip()

    @classmethod
    def _normalized_header(cls, value):
        return re.sub(r"\s+", " ", cls._clean_cell(value).casefold())

    @classmethod
    def _reference_column(cls, headers, target_language):
        preferred_languages = [
            language
            for language in ("PTBR", "SPA", "FRA")
            if language != target_language
        ]
        for language in preferred_languages:
            for index, header in enumerate(headers):
                if header in cls.TRANSLATION_HEADERS[language]:
                    return index, language
        return None, None

    @classmethod
    def from_general_json(cls, path, target_language):
        target_language = normalize_language_code(target_language)
        path = Path(path)
        with path.open("r", encoding="utf-8") as glossary_file:
            raw_data = json.load(glossary_file)
        if not isinstance(raw_data, dict):
            raise ValueError(f"The general glossary must be a JSON object: {path}")

        entries = []
        for english, translations in raw_data.items():
            if not isinstance(english, str) or not isinstance(translations, dict):
                continue
            english = english.strip()
            if not english:
                continue
            target = translations.get(target_language)
            target = target.strip() if isinstance(target, str) else ""
            reference = ""
            reference_language = ""
            if not target:
                for language in ("PTBR", "SPA", "FRA"):
                    if language == target_language:
                        continue
                    candidate = translations.get(language)
                    if isinstance(candidate, str) and candidate.strip():
                        reference = candidate.strip()
                        reference_language = language
                        break
            if target or reference:
                entries.append(
                    {
                        "english": english,
                        "translation": target,
                        "context": "",
                        "reference_translation": reference,
                        "reference_language": reference_language,
                    }
                )
        if not entries:
            raise ValueError(
                f"The general glossary has no usable entries for {target_language}: {path}"
            )
        return cls("General glossary", 1, path, entries, target_language)

    @classmethod
    def from_markdown(cls, path, target_language, name, priority):
        target_language = normalize_language_code(target_language)
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Glossary not found: {path}")

        entries = []
        column_state = None
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                column_state = None
                continue
            if not (stripped.startswith("|") and stripped.endswith("|")):
                continue
            cells = [cls._clean_cell(cell) for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue

            headers = [cls._normalized_header(cell) for cell in cells]
            english_index = next(
                (index for index, header in enumerate(headers) if header in cls.ENGLISH_HEADERS),
                None,
            )
            if english_index is not None:
                target_index = next(
                    (
                        index
                        for index, header in enumerate(headers)
                        if header in cls.TRANSLATION_HEADERS[target_language]
                    ),
                    None,
                )
                reference_index, reference_language = cls._reference_column(
                    headers, target_language
                )
                context_index = next(
                    (
                        index
                        for index, header in enumerate(headers)
                        if header in cls.CONTEXT_HEADERS
                    ),
                    None,
                )
                if target_index is None and reference_index is None:
                    raise ValueError(
                        f"The Markdown glossary has no recognized translation column: {path}"
                    )
                column_state = (
                    english_index,
                    target_index,
                    reference_index,
                    reference_language,
                    context_index,
                )
                continue

            if column_state is None:
                continue
            (
                english_index,
                target_index,
                reference_index,
                reference_language,
                context_index,
            ) = column_state
            required_indexes = [english_index]
            required_indexes.extend(
                index for index in (target_index, reference_index) if index is not None
            )
            if len(cells) <= max(required_indexes):
                continue
            english = cells[english_index].strip()
            translation = cells[target_index].strip() if target_index is not None else ""
            reference_translation = (
                cells[reference_index].strip() if reference_index is not None else ""
            )
            context = (
                cells[context_index].strip()
                if context_index is not None and len(cells) > context_index
                else ""
            )
            if english and (translation or reference_translation):
                entries.append(
                    {
                        "english": english,
                        "translation": translation,
                        "context": context,
                        "reference_translation": reference_translation,
                        "reference_language": reference_language or "",
                    }
                )

        if not entries:
            raise ValueError(f"The glossary has no usable Markdown entries: {path}")
        cls._validate_conflicts(entries, path)
        return cls(name, priority, path, entries, target_language)

    @staticmethod
    def _validate_conflicts(entries, path):
        approved = {}
        for entry in entries:
            key = (entry["english"].casefold(), entry.get("context", "").casefold())
            value = entry.get("translation") or entry.get("reference_translation") or ""
            previous = approved.get(key)
            if previous is not None and previous.casefold() != value.casefold():
                raise ValueError(
                    "The Markdown glossary has conflicting translations for "
                    f"'{entry['english']}' in context '{entry.get('context', '')}': {path}"
                )
            approved[key] = value

    def relevant_entries(self, english_content):
        content = str(english_content or "").casefold()
        return [
            dict(entry)
            for entry in self.entries
            if entry["english"].casefold() in content
        ]


class CSEGlossaryStack:
    """Load the independently run CSE glossary agents in priority order."""

    def __init__(self, layers):
        self.layers = sorted(list(layers), key=lambda layer: layer.priority)

    @staticmethod
    def global_sd_path(hub_dir):
        glossary_dir = Path(hub_dir) / "Glossary" / "sd_glossaries"
        candidates = sorted(glossary_dir.glob("global-sd-glossary*.md"))
        if not candidates:
            raise FileNotFoundError(
                f"No global-sd-glossary Markdown file was found in {glossary_dir}."
            )
        return candidates[0]

    @classmethod
    def load(cls, hub_dir, target_language, course_glossary_path=None):
        hub_dir = Path(hub_dir)
        target_language = normalize_language_code(target_language)
        layers = [
            CSEGlossaryLayer.from_general_json(
                hub_dir / "Glossary" / "glossary.json", target_language
            ),
            CSEGlossaryLayer.from_markdown(
                cls.global_sd_path(hub_dir),
                target_language,
                "Global software-development glossary",
                2,
            ),
        ]
        if course_glossary_path:
            layers.append(
                CSEGlossaryLayer.from_markdown(
                    Path(course_glossary_path).expanduser(),
                    target_language,
                    "Course-specific glossary",
                    3,
                )
            )
        return cls(layers)
