import json
import os
import re

import google.generativeai as genai  # type: ignore

from bots.api_utils import call_gemini_with_retry


class MarkdownTranslationBot:
    """Translate Markdown/MDX prose while restoring protected syntax exactly."""

    PLACEHOLDER_PREFIX = "@@GITHUB_PROTECTED_"

    def __init__(self, api_key=None, target_language="PTBR", log_func=print, model=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.target_language = target_language.upper()
        self.log = log_func
        if self.target_language != "PTBR":
            raise ValueError("Markdown GitHub translation currently supports PTBR only.")
        if self.api_key:
            genai.configure(api_key=self.api_key)
        self.client_ready = bool(self.api_key or model)
        self.model = model or genai.GenerativeModel("gemini-3.5-flash")

    @classmethod
    def _protect(cls, content: str) -> tuple[str, dict]:
        protected = {}

        def replace(match):
            placeholder = f"{cls.PLACEHOLDER_PREFIX}{len(protected):06d}@@"
            protected[placeholder] = match.group(0)
            return placeholder

        # Frontmatter is configuration, not student-facing prose.
        content = re.sub(r"\A---\s*\n.*?\n---\s*(?=\n)", replace, content, flags=re.DOTALL)
        content = re.sub(
            r"(?ms)^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*$",
            replace,
            content,
        )
        content = re.sub(r"(?m)(?:^(?: {4}|\t).*(?:\n|$))+", replace, content)
        content = re.sub(r"(?m)^(?:import|export)\s+.*$", replace, content)
        content = re.sub(r"(?<!`)`[^`\n]+`(?!`)", replace, content)
        content = re.sub(r"\{[^{}\n]*\}", replace, content)
        content = re.sub(r"<[^>\n]+>", replace, content)

        # Protect Markdown link/image destinations while allowing labels and alt
        # text to be translated.
        destination_pattern = re.compile(r"(?<=\]\()([^)\s]+)(?=(?:\s+['\"][^)]*['\"])?\))")
        content = destination_pattern.sub(replace, content)
        content = re.sub(r"https?://[^\s)>]+", replace, content)
        return content, protected

    @classmethod
    def _restore(cls, translated: str, protected: dict) -> str:
        for placeholder, original in protected.items():
            if placeholder not in translated:
                raise ValueError(f"Gemini omitted protected placeholder {placeholder}.")
            translated = translated.replace(placeholder, original)
        leaked = re.findall(r"@@GITHUB_PROTECTED_\d+@@", translated)
        if leaked:
            raise ValueError(f"Unrecognized protected placeholders remain: {leaked[:3]}")
        return translated

    @staticmethod
    def _strip_fence(output: str) -> str:
        stripped = output.strip()
        match = re.fullmatch(r"```(?:markdown|md|mdx)?\s*\n(.*)\n```", stripped, flags=re.DOTALL | re.IGNORECASE)
        return match.group(1) if match else stripped

    @staticmethod
    def _has_translatable_prose(protected_content: str) -> bool:
        without_placeholders = re.sub(r"@@GITHUB_PROTECTED_\d+@@", "", protected_content)
        words = re.findall(r"[A-Za-z]{2,}", without_placeholders)
        return len(words) >= 2

    @staticmethod
    def _chunks(content: str, limit=12000) -> list[str]:
        if len(content) <= limit:
            return [content]
        parts = re.split(r"(?<=\n\n)", content)
        chunks = []
        current = ""
        for part in parts:
            if current and len(current) + len(part) > limit:
                chunks.append(current)
                current = ""
            current += part
        if current:
            chunks.append(current)
        return chunks

    def translate(self, content: str, glossary_entries=None, page_title="Unknown") -> str:
        if not self.client_ready:
            raise RuntimeError("Markdown translation cannot run because GEMINI_API_KEY is missing.")
        protected_content, protected = self._protect(content)
        if not self._has_translatable_prose(protected_content):
            self.log(f"[MarkdownBot] No translatable prose found in {page_title}; preserving file.")
            return content

        glossary = json.dumps(glossary_entries or [], ensure_ascii=False, indent=2)
        chunks = self._chunks(protected_content)
        last_error = None
        for attempt in range(3):
            try:
                translated_chunks = []
                for index, chunk in enumerate(chunks, start=1):
                    if not self._has_translatable_prose(chunk):
                        translated_chunks.append(chunk)
                        continue
                    prompt = (
                        "You are an expert academic and software-development translator. Translate all "
                        "human-readable English prose into natural Brazilian Portuguese. Preserve Markdown "
                        "and MDX structure exactly. Never modify, translate, remove, duplicate, or reorder "
                        "tokens beginning with @@GITHUB_PROTECTED_. Do not add commentary or wrap the result "
                        "in a code fence. Translate image alt text and link labels. Preserve executable "
                        "identifiers and technical syntax. Apply the contextual glossary entries exactly "
                        "when their contexts match.\n\n"
                        f"PAGE: {page_title}\nCHUNK: {index}/{len(chunks)}\n"
                        f"GLOSSARY:\n{glossary}\n\nCONTENT:\n{chunk}"
                    )
                    response = call_gemini_with_retry(self.model, prompt, log_func=self.log)
                    output_chunk = self._strip_fence(response.text or "")
                    leading = chunk[:len(chunk) - len(chunk.lstrip())]
                    trailing = chunk[len(chunk.rstrip()):]
                    translated_chunks.append(f"{leading}{output_chunk.strip()}{trailing}")
                output = "".join(translated_chunks)
                restored = self._restore(output, protected)
                if not restored.strip():
                    raise ValueError("Gemini returned empty Markdown.")
                return restored.replace("\u00a0", " ").replace("&nbsp;", " ")
            except Exception as error:
                last_error = error
                self.log(f"[MarkdownBot] Attempt {attempt + 1}/3 failed for {page_title}: {error}")
        raise RuntimeError(f"Markdown translation failed for {page_title}: {last_error}")
