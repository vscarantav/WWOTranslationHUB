import re
from pathlib import Path

from bs4 import BeautifulSoup


class GitHubContentValidator:
    """Validate translated files without mutating either repository tree."""

    PLACEHOLDER_PATTERN = re.compile(r"@@GITHUB_PROTECTED_\d+@@")
    ENGLISH_WEEK_LABEL_PATTERN = re.compile(r"\bW\d{1,2}\b|\bWeek\s+\d{1,2}\b", re.IGNORECASE)

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

    @classmethod
    def _visible_english_week_labels(cls, content: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(["pre", "code", "script", "style", "noscript"]):
            tag.decompose()
        return cls.ENGLISH_WEEK_LABEL_PATTERN.findall(soup.get_text(" ", strip=True))

    def validate(self, original_content: str, translated_content: str, extension: str) -> list[str]:
        errors = []
        extension = extension.lower()
        if not translated_content.strip():
            errors.append("Translated content is empty.")
            return errors
        if len(translated_content) < max(1, int(len(original_content) * 0.2)):
            errors.append("Translated content is dangerously shorter than the source.")
        if self.PLACEHOLDER_PATTERN.search(translated_content):
            errors.append("A protected-content placeholder leaked into the output.")

        if extension in {".md", ".markdown", ".mdx"}:
            if self._markdown_code(original_content) != self._markdown_code(translated_content):
                errors.append("Markdown code blocks or inline code changed during translation.")
        elif extension in {".html", ".htm"}:
            if self._html_code(original_content) != self._html_code(translated_content):
                errors.append("HTML code/script/style content changed during translation.")
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
            try:
                BeautifulSoup(translated_content, "xml")
            except Exception as error:
                errors.append(f"Translated XML could not be parsed: {error}")
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
