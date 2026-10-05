import json
import os
import re

import google.generativeai as genai  # type: ignore
from bs4 import BeautifulSoup

from bots.api_utils import call_gemini_with_retry


RESERVED_WORDS = {
    "and", "as", "async", "await", "break", "case", "catch", "class",
    "const", "continue", "def", "delete", "do", "else", "except", "false",
    "finally", "for", "from", "function", "if", "import", "in", "is", "let",
    "new", "none", "not", "null", "or", "pass", "raise", "return", "select",
    "static", "switch", "this", "throw", "true", "try", "typeof", "var", "while",
    "with", "yield",
}


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
        ]
        for index, pattern in enumerate(patterns):
            for match in re.finditer(pattern, code):
                value = match.group(1)
                if index == 4:
                    for parameter in value.split(","):
                        name = re.sub(r"[:=].*$", "", parameter).strip().lstrip("* ")
                        if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                            candidates.add(name)
                else:
                    candidates.add(value)
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
            "identifier using the same naming style as the original. Reuse EXISTING MAPPINGS "
            "exactly whenever present.\n\n"
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
                        by_original[original] = {
                            "page_title": page_title,
                            "context_summary": context,
                            "variable_en": original,
                            "variable_pt": existing_mapping.get(original, translated),
                            "source_file": source_file,
                        }
                missing = expected - set(by_original)
                if missing:
                    raise ValueError(f"Gemini omitted variables: {', '.join(sorted(missing))}")
                return [by_original[candidate] for candidate in candidates]
            except Exception as error:
                last_error = error
                self.log(f"[VariableBot] Attempt {attempt + 1}/3 failed for {source_file}: {error}")
        raise RuntimeError(f"Variable analysis failed for {source_file}: {last_error}")
