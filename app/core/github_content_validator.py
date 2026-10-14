import ast
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree

from bots.variable_extraction import VariableApplicationError, VariableTranslator


class GitHubContentValidator:
    """Validate translated files without mutating either repository tree."""

    PLACEHOLDER_PATTERN = re.compile(r"@@GITHUB_PROTECTED_\d+@@")
    ENGLISH_WEEK_LABEL_PATTERN = re.compile(r"\bW\d{1,2}\b|\bWeek\s+\d{1,2}\b", re.IGNORECASE)
    DEPRECATED_LEARNING_ACTIVITY_PATTERN = re.compile(
        r"\batividades?\s+de\s+aprendizado\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _markdown_code(content: str) -> list[str]:
        complete_blocks = []
        pattern = re.compile(r"(?ms)^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*$")
        for match in pattern.finditer(content):
            complete_blocks.append(match.group(0))
        complete_blocks.extend(
            match.group(0)
            for match in re.finditer(r"(?m)(?:^(?: {4}|\t).*(?:\n|$))+", content)
        )
        inline = [match.group(0) for match in re.finditer(r"(?<!`)`[^`\n]+`(?!`)", content)]
        return complete_blocks + inline

    @staticmethod
    def _html_code(content: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        return [str(tag) for tag in soup.find_all(["pre", "code", "script", "style"])]

    @staticmethod
    def _markup_structure(content: str, extension: str) -> list[tuple]:
        """Capture tag nesting and non-translatable attributes in document order."""
        parser = "xml" if extension == ".xml" else "html.parser"
        soup = BeautifulSoup(content, parser)
        ignored_text_attributes = {"alt", "title", "aria-label", "placeholder"}
        structure = []
        for tag in soup.find_all(True):
            parents = tuple(parent.name for parent in tag.parents if parent.name != "[document]")
            attributes = []
            for name, value in sorted(tag.attrs.items()):
                if name in ignored_text_attributes:
                    continue
                if isinstance(value, list):
                    value = " ".join(value)
                attributes.append((name, str(value)))
            structure.append((parents, tag.name, tuple(attributes)))
        return structure

    @staticmethod
    def _markdown_structure(content: str) -> list[tuple]:
        """Capture line-level Markdown delimiters while allowing prose to change."""
        structure = []
        in_fence = False
        fence_marker = ""
        for line in content.splitlines():
            fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
            if fence:
                marker = fence.group(1)
                if not in_fence:
                    in_fence = True
                    fence_marker = marker[0]
                    structure.append(("fence-open", marker, fence.group(2).strip()))
                else:
                    structure.append(("fence-close", marker[0]))
                    if marker[0] == fence_marker:
                        in_fence = False
                        fence_marker = ""
                continue
            if in_fence:
                continue
            prefix = re.match(
                r"^(\s*)(#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)?",
                line,
            )
            marker = prefix.group(2) if prefix else None
            pipe_count = line.count("|") if "|" in line else 0
            link_destinations = tuple(
                match.group(1)
                for match in re.finditer(r"(?<!!)\[[^\]]*\]\(([^)\s]+)", line)
            )
            image_destinations = tuple(
                match.group(1)
                for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", line)
            )
            structure.append((bool(line.strip()), marker or "", pipe_count, link_destinations, image_destinations))
        return structure

    @staticmethod
    def _syntax_errors(content: str, extension: str) -> list[str]:
        """Use available parsers, falling back to approved-delta checks elsewhere."""
        errors = []
        if extension == ".xml":
            try:
                etree.fromstring(content.encode("utf-8"))
            except etree.XMLSyntaxError as error:
                errors.append(f"Translated XML is not well formed: {error}")

        snippets = []
        if extension in {".md", ".markdown", ".mdx"}:
            pattern = re.compile(
                r"(?ms)^(`{3,}|~{3,})([^\n]*)\n(.*?)^\1[ \t]*$"
            )
            snippets.extend(
                (match.group(2).strip().casefold(), match.group(3))
                for match in pattern.finditer(content)
            )
        elif extension in {".html", ".htm", ".xml"}:
            parser = "xml" if extension == ".xml" else "html.parser"
            soup = BeautifulSoup(content, parser)
            for tag in soup.find_all(["script", "code"]):
                language = str(tag.get("type") or "").casefold()
                classes = " ".join(tag.get("class") or []).casefold()
                snippets.append((f"{language} {classes}", tag.get_text("\n", strip=False)))

        for language, snippet in snippets:
            try:
                if language in {"py", "python"} or "python" in language:
                    ast.parse(snippet)
                elif language == "json" or "json" in language:
                    json.loads(snippet)
            except (SyntaxError, json.JSONDecodeError) as error:
                errors.append(f"Translated {language.strip() or 'code'} is invalid: {error}")
        return errors

    @staticmethod
    def _linked_attributes(content: str, extension: str) -> list[tuple[str, str, str]]:
        parser = "xml" if extension == ".xml" else "html.parser"
        soup = BeautifulSoup(content, parser)
        attributes = []
        for tag in soup.find_all(True):
            for attribute in sorted(VariableTranslator.LINKED_ATTRIBUTES):
                if tag.has_attr(attribute):
                    value = tag.get(attribute)
                    if isinstance(value, list):
                        value = " ".join(value)
                    attributes.append((tag.name, attribute, str(value)))
        return attributes

    @classmethod
    def _visible_english_week_labels(cls, content: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(["pre", "code", "script", "style", "noscript"]):
            tag.decompose()
        return cls.ENGLISH_WEEK_LABEL_PATTERN.findall(soup.get_text(" ", strip=True))

    def validate(
        self,
        original_content: str,
        translated_content: str,
        extension: str,
        variable_mapping: dict[str, str] | None = None,
    ) -> list[str]:
        errors = []
        extension = extension.lower()
        variable_mapping = dict(variable_mapping or {})
        expected_code_content = original_content
        if variable_mapping:
            try:
                expected_code_content, _ = VariableTranslator.apply(
                    original_content, extension, variable_mapping
                )
            except VariableApplicationError as error:
                errors.append(f"Invalid variable mapping: {error}")
        if not translated_content.strip():
            errors.append("Translated content is empty.")
            return errors
        if len(translated_content) < max(1, int(len(original_content) * 0.2)):
            errors.append("Translated content is dangerously shorter than the source.")
        if self.PLACEHOLDER_PATTERN.search(translated_content):
            errors.append("A protected-content placeholder leaked into the output.")
        if self.DEPRECATED_LEARNING_ACTIVITY_PATTERN.search(translated_content):
            errors.append(
                "Glossary violation: use 'atividade(s) de aprendizagem', never "
                "'atividade(s) de aprendizado'."
            )

        if extension in {".md", ".markdown", ".mdx"}:
            if self._markdown_code(expected_code_content) != self._markdown_code(translated_content):
                if variable_mapping:
                    errors.append(
                        "Markdown code differs from the approved Portuguese variable substitutions."
                    )
                else:
                    errors.append("Markdown code blocks or inline code changed during translation.")
            if self._markdown_structure(original_content) != self._markdown_structure(translated_content):
                errors.append("Markdown delimiters, list structure, or link destinations changed.")
        elif extension in {".html", ".htm"}:
            if self._html_code(expected_code_content) != self._html_code(translated_content):
                if variable_mapping:
                    errors.append(
                        "HTML code/script/style content differs from the approved Portuguese "
                        "variable substitutions."
                    )
                else:
                    errors.append("HTML code/script/style content changed during translation.")
            if variable_mapping and self._linked_attributes(
                expected_code_content, extension
            ) != self._linked_attributes(translated_content, extension):
                errors.append(
                    "HTML linked identifier attributes differ from the approved Portuguese "
                    "variable substitutions."
                )
            if self._markup_structure(expected_code_content, extension) != self._markup_structure(
                translated_content, extension
            ):
                errors.append("HTML tags or protected attributes changed during translation.")
            remaining_week_labels = self._visible_english_week_labels(translated_content)
            if remaining_week_labels:
                labels = ", ".join(sorted(set(remaining_week_labels), key=str.casefold))
                errors.append(
                    f"English week label(s) remain in visible HTML text: {labels}."
                )
            try:
                BeautifulSoup(translated_content, "html.parser")
            except Exception as error:
                errors.append(f"Translated HTML could not be parsed: {error}")
        elif extension == ".xml":
            if variable_mapping:
                expected_code = BeautifulSoup(expected_code_content, "xml")
                translated_code = BeautifulSoup(translated_content, "xml")
                expected_tags = [
                    str(tag) for tag in expected_code.find_all(["pre", "code", "script", "style"])
                ]
                translated_tags = [
                    str(tag) for tag in translated_code.find_all(["pre", "code", "script", "style"])
                ]
                if expected_tags != translated_tags:
                    errors.append(
                        "XML code content differs from the approved Portuguese variable substitutions."
                    )
                if self._linked_attributes(
                    expected_code_content, extension
                ) != self._linked_attributes(translated_content, extension):
                    errors.append(
                        "XML linked identifier attributes differ from the approved Portuguese "
                        "variable substitutions."
                    )
            if self._markup_structure(expected_code_content, extension) != self._markup_structure(
                translated_content, extension
            ):
                errors.append("XML tags or protected attributes changed during translation.")
        errors.extend(self._syntax_errors(translated_content, extension))
        return errors

    @staticmethod
    def validate_tree(source_root, translated_root, manifest) -> list[str]:
        source = Path(source_root).resolve()
        translated = Path(translated_root).resolve()
        errors = []
        if (translated / ".git").exists():
            errors.append("Translated tree inherited the source .git directory.")
        if (translated / ".github" / "workflows").exists():
            errors.append("Translated tree contains source GitHub workflows.")
        for item in manifest:
            if item.action == "ignored":
                continue
            source_path = source / item.relative_path
            translated_path = translated / item.relative_path
            if source_path.is_file() and not translated_path.is_file():
                errors.append(f"Output is missing {item.relative_path}.")
        return errors
