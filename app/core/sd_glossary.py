import re
from collections import defaultdict
from pathlib import Path


class SoftwareDevelopmentGlossary:
    """Read the approved Markdown global SD glossary with contextual duplicates."""

    PORTUGUESE_HEADERS = {"portuguese", "portuguese (brazil)", "português", "português (brasil)"}

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
            raise ValueError(f"The SD glossary has no Markdown table: {path}")

        headers = [header.casefold() for header in table_rows[0]]
        try:
            english_index = headers.index("english")
            target_index = next(
                index for index, header in enumerate(headers)
                if header in cls.PORTUGUESE_HEADERS
            )
        except (ValueError, StopIteration) as error:
            raise ValueError(
                "The global SD glossary must contain English and Portuguese (Brazil) columns."
            ) from error
        context_index = headers.index("context") if "context" in headers else None

        parsed = []
        for cells in table_rows[1:]:
            if len(cells) <= max(english_index, target_index):
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
            raise ValueError(f"The SD glossary has no usable Portuguese entries: {path}")
        approved = {}
        for row in parsed:
            key = (row["english"].casefold(), row["context"].casefold())
            previous = approved.get(key)
            if previous is not None and previous.casefold() != row["target"].casefold():
                raise ValueError(
                    "The global SD glossary has conflicting Portuguese values for "
                    f"'{row['english']}' in context '{row['context']}'."
                )
            approved[key] = row["target"]
        return cls(parsed, path)

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
