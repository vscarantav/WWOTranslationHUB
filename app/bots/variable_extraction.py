import json
import os
import re

import google.generativeai as genai  # type: ignore
from bs4 import BeautifulSoup, Comment, NavigableString

from bots.api_utils import call_gemini_with_retry


RESERVED_WORDS = {
    "and", "as", "async", "await", "break", "case", "catch", "class",
    "const", "continue", "def", "delete", "do", "else", "except", "false",
    "finally", "for", "from", "function", "global", "if", "import", "in", "instanceof",
    "interface", "is", "lambda", "let", "new", "nonlocal", "none", "not", "null", "or",
    "package", "pass", "private", "protected", "public", "raise", "return", "select",
    "static", "super", "switch", "this", "throw", "true", "try", "typeof", "var", "void",
    "while", "with", "yield",
}


class VariableApplicationError(ValueError):
    """Raised when an identifier mapping cannot be applied safely."""


class VariableTranslator:
    """Apply approved variable mappings only inside supported code contexts."""

    CODE_TAGS = {"pre", "code", "script"}
    LINKED_ATTRIBUTES = {
        "id", "name", "for", "aria-controls", "aria-labelledby", "aria-describedby"
    }
    IDENTIFIER_SEGMENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
    STRING_OR_COMMENT = re.compile(
        r"(?P<block_comment>/\*.*?\*/)"
        r"|(?P<line_comment>//[^\n]*|^[ \t]*\#[^\n]*)"
        r"|(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`)",
        flags=re.DOTALL | re.MULTILINE,
    )
    EMBEDDED_LINKED_ATTRIBUTE = re.compile(
        r"\b(?:id|name|for|aria-controls|aria-labelledby|aria-describedby)\s*=\s*"
        r"(?P<quote>['\"])(?P<value>[A-Za-z_$][A-Za-z0-9_$]*)(?P=quote)",
        flags=re.IGNORECASE,
    )

    @classmethod
    def _is_valid_identifier(cls, value: str) -> bool:
        return bool(value) and all(
            cls.IDENTIFIER_SEGMENT.fullmatch(segment)
            for segment in value.split(".")
        )

    @staticmethod
    def _identifier_style(value: str) -> str:
        """Classify a single identifier segment for source-style preservation."""
        prefix = "$" if value.startswith("$") else ""
        value = value[len(prefix):]
        if not value:
            return "invalid"
        if "_" in value:
            if value.upper() == value:
                return f"{prefix}upper_snake"
            if value.lower() == value:
                return f"{prefix}snake"
            return f"{prefix}mixed_snake"
        if value.upper() == value and any(character.isalpha() for character in value):
            return f"{prefix}upper"
        if value[:1].isupper():
            return f"{prefix}pascal"
        if any(character.isupper() for character in value[1:]):
            return f"{prefix}camel"
        return f"{prefix}lower"

    @classmethod
    def validate_mapping(cls, mapping: dict[str, str]) -> None:
        normalized = {
            str(original).strip(): str(translated).strip()
            for original, translated in dict(mapping or {}).items()
        }
        for original, translated in normalized.items():
            if not cls._is_valid_identifier(original):
                raise VariableApplicationError(
                    f"Invalid source identifier in variable mapping: {original!r}."
                )
            if not cls._is_valid_identifier(translated):
                raise VariableApplicationError(
                    f"Invalid Portuguese identifier for {original!r}: {translated!r}."
                )
            reserved_segments = [
                segment for segment in translated.split(".")
                if segment.casefold() in RESERVED_WORDS
            ]
            if reserved_segments:
                raise VariableApplicationError(
                    f"Portuguese identifier for {original!r} uses reserved word "
                    f"{reserved_segments[0]!r}."
                )
            original_segments = original.split(".")
            translated_segments = translated.split(".")
            if len(original_segments) != len(translated_segments):
                raise VariableApplicationError(
                    f"Portuguese identifier for {original!r} changes its dotted segment count."
                )
            for source_segment, target_segment in zip(original_segments, translated_segments):
                source_style = cls._identifier_style(source_segment)
                target_style = cls._identifier_style(target_segment)
                if source_style != target_style:
                    raise VariableApplicationError(
                        f"Portuguese identifier for {original!r} changes naming style "
                        f"from {source_style!r} to {target_style!r}."
                    )

        translated_to_originals = {}
        for original, translated in normalized.items():
            translated_to_originals.setdefault(translated, []).append(original)
        collisions = {
            translated: originals
            for translated, originals in translated_to_originals.items()
            if len(set(originals)) > 1
        }
        if collisions:
            translated, originals = next(iter(collisions.items()))
            raise VariableApplicationError(
                f"Variable mapping collision: {', '.join(sorted(originals))} all map to "
                f"{translated!r}."
            )

    @staticmethod
    def _effective_mapping(mapping: dict[str, str]) -> dict[str, str]:
        return {
            str(original).strip(): str(translated).strip()
            for original, translated in dict(mapping or {}).items()
            if str(original).strip() and str(original).strip() != str(translated).strip()
        }

    @classmethod
    def _replace_identifiers(cls, text: str, mapping: dict[str, str]):
        effective = cls._effective_mapping(mapping)
        counts = {original: 0 for original in effective}
        if not effective or not text:
            return text, counts
        alternatives = "|".join(
            re.escape(original)
            for original in sorted(effective, key=lambda value: (-len(value), value))
        )
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_])(?P<identifier>{alternatives})(?![A-Za-z0-9_])"
        )

        def replace(match):
            original = match.group("identifier")
            counts[original] += 1
            return effective[original]

        return pattern.sub(replace, text), counts

    @classmethod
    def _replace_code_text(
        cls,
        text: str,
        mapping: dict[str, str],
        linked_identifiers=None,
    ):
        """Rename code tokens while preserving comments and unrelated string literals."""
        effective = cls._effective_mapping(mapping)
        total = {original: 0 for original in effective}
        if not effective or not text:
            return text, total

        linked = set(linked_identifiers or ())
        linked.update(
            match.group("value")
            for match in cls.EMBEDDED_LINKED_ATTRIBUTE.finditer(text)
        )
        pieces = []
        cursor = 0
        for match in cls.STRING_OR_COMMENT.finditer(text):
            code, counts = cls._replace_identifiers(text[cursor:match.start()], mapping)
            cls._merge_counts(total, counts)
            pieces.append(code)
            token = match.group(0)
            if match.lastgroup == "string":
                quote = token[0]
                value = token[1:-1]
                replacement = value
                if value in linked and value in effective:
                    replacement = effective[value]
                    total[value] = total.get(value, 0) + 1
                elif value[:1] in {"#", "."} and value[1:] in linked and value[1:] in effective:
                    original = value[1:]
                    replacement = value[0] + effective[original]
                    total[original] = total.get(original, 0) + 1
                elif quote == "`" and "${" in value:
                    def replace_expression(expression_match):
                        expression, expression_counts = cls._replace_identifiers(
                            expression_match.group(1), mapping
                        )
                        cls._merge_counts(total, expression_counts)
                        return "${" + expression + "}"

                    replacement = re.sub(r"\$\{([^{}]*)\}", replace_expression, value)
                pieces.append(quote + replacement + quote)
            else:
                pieces.append(token)
            cursor = match.end()
        code, counts = cls._replace_identifiers(text[cursor:], mapping)
        cls._merge_counts(total, counts)
        pieces.append(code)
        return "".join(pieces), total

    @staticmethod
    def _merge_counts(total: dict[str, int], addition: dict[str, int]) -> None:
        for original, count in addition.items():
            total[original] = total.get(original, 0) + count

    @classmethod
    def _markdown_spans(cls, content: str) -> list[tuple[int, int]]:
        spans = []
        blocked = []
        fenced = re.compile(
            r"(?ms)^(?P<fence>`{3,}|~{3,})[^\n]*\n(?P<body>.*?)^(?P=fence)[ \t]*$"
        )
        for match in fenced.finditer(content):
            spans.append(match.span("body"))
            blocked.append(match.span(0))

        indented = re.compile(r"(?m)(?:^(?: {4}|\t).*(?:\n|$))+")
        for match in indented.finditer(content):
            if any(start < match.end() and match.start() < end for start, end in blocked):
                continue
            spans.append(match.span(0))
            blocked.append(match.span(0))

        inline = re.compile(r"(?<!`)`(?P<body>[^`\n]+)`(?!`)")
        for match in inline.finditer(content):
            if any(start < match.end() and match.start() < end for start, end in blocked):
                continue
            spans.append(match.span("body"))
        return sorted(spans)

    @classmethod
    def _apply_markdown(cls, content: str, mapping: dict[str, str]):
        total = {original: 0 for original in cls._effective_mapping(mapping)}
        rewritten = content
        for start, end in reversed(cls._markdown_spans(content)):
            replacement, counts = cls._replace_code_text(content[start:end], mapping)
            rewritten = rewritten[:start] + replacement + rewritten[end:]
            cls._merge_counts(total, counts)
        return rewritten, total

    @classmethod
    def _apply_markup(cls, content: str, extension: str, mapping: dict[str, str]):
        parser = "xml" if extension == ".xml" else "html.parser"
        soup = BeautifulSoup(content, parser)
        total = {original: 0 for original in cls._effective_mapping(mapping)}
        changed = False
        linked_identifiers = set()
        for tag in soup.find_all(True):
            for attribute in cls.LINKED_ATTRIBUTES:
                value = tag.get(attribute)
                if value is None:
                    continue
                values = value if isinstance(value, list) else str(value).split()
                linked_identifiers.update(values)

        for tag in soup.find_all(list(cls.CODE_TAGS)):
            if tag.find_parent(list(cls.CODE_TAGS)) is not None:
                continue
            for node in list(tag.find_all(string=True)):
                if isinstance(node, Comment) or not isinstance(node, NavigableString):
                    continue
                replacement, counts = cls._replace_code_text(
                    str(node), mapping, linked_identifiers
                )
                cls._merge_counts(total, counts)
                if replacement != str(node):
                    node.replace_with(replacement)
                    changed = True

        effective = cls._effective_mapping(mapping)
        for tag in soup.find_all(True):
            for attribute in cls.LINKED_ATTRIBUTES:
                value = tag.get(attribute)
                if value is None:
                    continue
                values = value if isinstance(value, list) else str(value).split()
                translated_values = [effective.get(item, item) for item in values]
                if translated_values == values:
                    continue
                tag[attribute] = translated_values if isinstance(value, list) else " ".join(translated_values)
                for item in values:
                    if item in effective:
                        total[item] = total.get(item, 0) + 1
                changed = True

        return (str(soup) if changed else content), total

    @classmethod
    def apply(cls, content: str, extension: str, mapping: dict[str, str]):
        """Return rewritten content and replacement counts by English identifier."""
        mapping = dict(mapping or {})
        cls.validate_mapping(mapping)
        extension = extension.lower()
        if not cls._effective_mapping(mapping):
            return content, {}
        if extension in {".md", ".markdown", ".mdx"}:
            return cls._apply_markdown(content, mapping)
        if extension in {".html", ".htm", ".xml"}:
            return cls._apply_markup(content, extension, mapping)
        if extension == ".txt":
            return cls._replace_code_text(content, mapping)
        raise VariableApplicationError(
            f"Variable translation is not supported for {extension or 'this file type'}."
        )


class VariableExtractor:
    """Find likely variable identifiers in instructional code examples."""

    @staticmethod
    def code_fragments(content: str, extension: str) -> list[str]:
        extension = extension.lower()
        fragments = []
        if extension in {".md", ".markdown", ".mdx"}:
            pattern = re.compile(r"(?ms)^(?P<fence>`{3,}|~{3,})[^\n]*\n(.*?)^(?P=fence)[ \t]*$")
            fragments.extend(match.group(2) for match in pattern.finditer(content))
            fragments.extend(match.group(1) for match in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", content))
        elif extension in {".html", ".htm", ".xml"}:
            soup = BeautifulSoup(content, "xml" if extension == ".xml" else "html.parser")
            fragments.extend(tag.get_text("\n", strip=False) for tag in soup.find_all(["pre", "code", "script"]))
        elif extension == ".txt":
            fragments.append(content)
        return [fragment for fragment in fragments if fragment.strip()]

    @staticmethod
    def candidates_from_code(code: str) -> set[str]:
        candidates = set()
        patterns = [
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)",
            r"(?m)^\s*([A-Za-z_][\w]*)\s*=(?!=)",
            r"\bfor\s*\(?(?:const|let|var)?\s*([A-Za-z_$][\w$]*)\s+(?:in|of)\b",
            r"\bfor\s+([A-Za-z_][\w]*)\s+in\b",
            r"\b(?:def|function)\s+[A-Za-z_$][\w$]*\s*\(([^)]*)\)",
            r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}",
            r"\$\{\s*([A-Za-z_$][\w$]*)\s*\}",
            r"\$([A-Z][A-Z0-9_]*)\b",
            r"\b(?:CREATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|UPDATE|FROM|JOIN)\s+([A-Za-z_][\w]*)",
            r"(?:^|[,{]\s*)([A-Za-z_$][\w$]*)\s*:(?!=)",
        ]
        for index, pattern in enumerate(patterns):
            flags = re.IGNORECASE if index == 8 else 0
            for match in re.finditer(pattern, code, flags=flags):
                value = match.group(1)
                if index == 4:
                    for parameter in value.split(","):
                        name = re.sub(r"[:=].*$", "", parameter).strip().lstrip("* ")
                        if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                            candidates.add(name)
                else:
                    candidates.add(value)
        for table_body in re.finditer(
            r"\bCREATE\s+TABLE\s+[A-Za-z_][\w]*\s*\((.*?)\)",
            code,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            for definition in table_body.group(1).split(","):
                column = re.match(r"\s*([A-Za-z_][\w]*)\s+", definition)
                if column and column.group(1).casefold() not in {
                    "constraint", "primary", "foreign", "unique", "check"
                }:
                    candidates.add(column.group(1))
        return {
            candidate
            for candidate in candidates
            if candidate.casefold() not in RESERVED_WORDS and len(candidate) > 1
        }

    @classmethod
    def extract(cls, content: str, extension: str) -> tuple[list[str], list[str]]:
        fragments = cls.code_fragments(content, extension)
        candidates = set()
        for fragment in fragments:
            candidates.update(cls.candidates_from_code(fragment))
        return fragments, sorted(candidates, key=str.casefold)


class VariableAnalysisBot:
    """Ask Gemini for consistent target-language names for detected variables."""

    def __init__(self, api_key=None, target_language="PTBR", log_func=print, model=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.target_language = target_language.upper()
        self.log = log_func
        if self.target_language != "PTBR":
            raise ValueError("Variable analysis currently supports PTBR only.")
        if self.api_key:
            genai.configure(api_key=self.api_key)
        self.client_ready = bool(self.api_key or model)
        self.model = model or genai.GenerativeModel("gemini-3.5-flash")

    @staticmethod
    def _parse_json(text: str):
        stripped = (text or "").strip()
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
        return json.loads(stripped)

    def analyze(self, content: str, extension: str, page_title: str, source_file: str, existing_mapping=None):
        fragments, candidates = VariableExtractor.extract(content, extension)
        if not candidates:
            return []
        if not self.client_ready:
            raise RuntimeError("Variable analysis cannot run because GEMINI_API_KEY is missing.")

        existing_mapping = dict(existing_mapping or {})
        code_payload = "\n\n--- CODE FRAGMENT ---\n".join(fragments)
        prompt = (
            "Analyze the programming/configuration/database identifiers in the supplied code. "
            "Do not rewrite the code. Return ONLY a JSON object with a 'variables' array. Every "
            "candidate must appear exactly once. Each item must contain 'original', "
            "'translated', and 'context_summary'. Suggest a concise Brazilian Portuguese "
            "identifier using ASCII characters only and the same naming style as the original. "
            "The translated identifier will be applied to executable examples, so it must be a "
            "valid non-reserved identifier. Reuse EXISTING MAPPINGS exactly whenever present.\n\n"
            f"PAGE TITLE: {page_title}\nSOURCE FILE: {source_file}\n"
            f"CANDIDATES: {json.dumps(candidates, ensure_ascii=False)}\n"
            f"EXISTING MAPPINGS: {json.dumps(existing_mapping, ensure_ascii=False)}\n"
            f"CODE:\n{code_payload}"
        )
        last_error = None
        expected = set(candidates)
        for attempt in range(3):
            try:
                response = call_gemini_with_retry(self.model, prompt, log_func=self.log)
                payload = self._parse_json(response.text or "")
                variables = payload.get("variables")
                if not isinstance(variables, list):
                    raise ValueError("Response has no variables array.")
                by_original = {}
                for item in variables:
                    original = str(item.get("original", "")).strip()
                    translated = str(item.get("translated", "")).strip()
                    context = str(item.get("context_summary", "")).strip()
                    if original in expected and translated and context:
                        selected_translation = existing_mapping.get(original, translated)
                        VariableTranslator.validate_mapping({original: selected_translation})
                        by_original[original] = {
                            "page_title": page_title,
                            "context_summary": context,
                            "variable_en": original,
                            "variable_pt": selected_translation,
                            "source_file": source_file,
                        }
                missing = expected - set(by_original)
                if missing:
                    raise ValueError(f"Gemini omitted variables: {', '.join(sorted(missing))}")
                merged_mapping = dict(existing_mapping)
                merged_mapping.update({
                    original: row["variable_pt"]
                    for original, row in by_original.items()
                })
                VariableTranslator.validate_mapping(merged_mapping)
                return [by_original[candidate] for candidate in candidates]
            except Exception as error:
                last_error = error
                self.log(f"[VariableBot] Attempt {attempt + 1}/3 failed for {source_file}: {error}")
        raise RuntimeError(f"Variable analysis failed for {source_file}: {last_error}")
