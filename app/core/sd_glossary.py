import json
import re
from collections import defaultdict
from pathlib import Path


class SoftwareDevelopmentGlossary:
    """Read and prioritize the glossaries used by GitHub translation."""

    ENGLISH_HEADERS = {"english", "english term"}
    PORTUGUESE_HEADERS = {
        "portuguese",
        "portuguese (brazil)",
        "português",
        "português (brasil)",
        "pt-br translation",
        "ptbr translation",
        "portuguese translation",
    }

    def __init__(self, rows=None, source_path=None):
        self.rows = list(rows or [])
        self.source_path = str(source_path) if source_path else ""

    @staticmethod
    def default_path(hub_dir):
        glossary_dir = Path(hub_dir) / "Glossary" / "sd_glossaries"
        candidates = sorted(glossary_dir.glob("global-sd-glossary*.md"))
        if not candidates:
            raise FileNotFoundError(
                f"No global-sd-glossary Markdown file was found in {glossary_dir}."
            )
        return candidates[0]

    @staticmethod
    def general_path(hub_dir):
        return Path(hub_dir) / "Glossary" / "glossary.json"

    @classmethod
    def load_general(cls, filepath, target_language="PTBR"):
        if target_language.upper() != "PTBR":
            raise ValueError("The GitHub flow supports PTBR only until the Spanish SD glossary is ready.")
        path = Path(filepath)
        with path.open("r", encoding="utf-8") as glossary_file:
            raw_data = json.load(glossary_file)
        if not isinstance(raw_data, dict):
            raise ValueError(f"The general glossary must be a JSON object: {path}")

        parsed = []
        for english, translations in raw_data.items():
            if not isinstance(translations, dict):
                continue
            target = translations.get(target_language.upper())
            if isinstance(english, str) and isinstance(target, str):
                english = english.strip()
                target = target.strip()
                if english and target:
                    parsed.append({"english": english, "target": target, "context": ""})
        if not parsed:
            raise ValueError(f"The general glossary has no usable {target_language.upper()} entries: {path}")
        return cls(parsed, path)

    @classmethod
    def load(cls, filepath, target_language="PTBR"):
        if target_language.upper() != "PTBR":
            raise ValueError("The GitHub flow supports PTBR only until the Spanish SD glossary is ready.")
        path = Path(filepath)
        lines = path.read_text(encoding="utf-8").splitlines()
        table_rows = []
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|") or not stripped.endswith("|"):
                continue
            cells = [re.sub(r"\*\*", "", cell.strip()) for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            table_rows.append(cells)
        if not table_rows:
            raise ValueError(f"The glossary has no Markdown table: {path}")

        headers = [header.casefold() for header in table_rows[0]]
        try:
            english_index = next(
                index for index, header in enumerate(headers)
                if header in cls.ENGLISH_HEADERS
            )
            target_index = next(
                index for index, header in enumerate(headers)
                if header in cls.PORTUGUESE_HEADERS
            )
        except StopIteration as error:
            raise ValueError(
                "The Markdown glossary must contain English and Portuguese translation columns."
            ) from error
        context_index = headers.index("context") if "context" in headers else None

        parsed = []
        for cells in table_rows[1:]:
            if len(cells) <= max(english_index, target_index):
                continue
            if (
                cells[english_index].strip().casefold() in cls.ENGLISH_HEADERS
                and cells[target_index].strip().casefold() in cls.PORTUGUESE_HEADERS
            ):
                continue
            english = cells[english_index].strip()
            target = cells[target_index].strip()
            context = (
                cells[context_index].strip()
                if context_index is not None and len(cells) > context_index
                else ""
            )
            if english and target:
                parsed.append({"english": english, "target": target, "context": context})
        if not parsed:
            raise ValueError(f"The glossary has no usable Portuguese entries: {path}")
        approved = {}
        for row in parsed:
            key = (row["english"].casefold(), row["context"].casefold())
            previous = approved.get(key)
            if previous is not None and previous.casefold() != row["target"].casefold():
                raise ValueError(
                    "The Markdown glossary has conflicting Portuguese values for "
                    f"'{row['english']}' in context '{row['context']}'."
                )
            approved[key] = row["target"]
        return cls(parsed, path)

    @classmethod
    def combine_by_priority(cls, *glossaries):
        """Combine low-to-high priority glossaries, replacing whole term groups."""
        selected_rows = {}
        selected_order = []
        source_paths = []
        for glossary in glossaries:
            if glossary.source_path:
                source_paths.append(glossary.source_path)
            layer_rows = defaultdict(list)
            layer_order = []
            for row in glossary.rows:
                key = row["english"].casefold()
                if key not in layer_rows:
                    layer_order.append(key)
                layer_rows[key].append(dict(row))
            for key in layer_order:
                if key not in selected_rows:
                    selected_order.append(key)
                selected_rows[key] = layer_rows[key]
        rows = [row for key in selected_order for row in selected_rows[key]]
        return cls(rows, "; ".join(source_paths))

    @classmethod
    def load_github_stack(cls, hub_dir, course_glossary_path, target_language="PTBR"):
        general = cls.load_general(cls.general_path(hub_dir), target_language)
        software_development = cls.load(cls.default_path(hub_dir), target_language)
        if not course_glossary_path:
            return cls.combine_by_priority(general, software_development)

        course_path = Path(course_glossary_path).expanduser()
        if not course_path.is_file():
            raise FileNotFoundError(f"Course-specific glossary not found: {course_path}")
        course = cls.load(course_path, target_language)
        return cls.combine_by_priority(general, software_development, course)

    def relevant_entries(self, content: str) -> list[dict]:
        content_lower = content.casefold()
        return [
            dict(row)
            for row in self.rows
            if row["english"].casefold() in content_lower
        ]

    def relevant_mapping(self, content: str) -> dict:
        grouped = defaultdict(list)
        for row in self.relevant_entries(content):
            detail = row["target"]
            if row.get("context"):
                detail += f" (context: {row['context']})"
            grouped[row["english"]].append(detail)
        return {
            english: values[0] if len(values) == 1 else values
            for english, values in grouped.items()
        }
