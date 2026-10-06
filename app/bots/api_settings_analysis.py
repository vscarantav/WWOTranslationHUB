import json
import os
import re

import google.generativeai as genai  # type: ignore
from bs4 import BeautifulSoup

from bots.api_utils import call_gemini_with_retry


class APISettingsAnalysisBot:
    """Identify actionable API and external-service configuration instructions."""

    CANDIDATE_PATTERN = re.compile(
        r"(?:\bapi\b|api[_ -]?(?:key|token|endpoint)|\.env\b|environment variables?|"
        r"client[_ -]?(?:id|secret)|access token|base url|build command|publish directory|"
        r"start command|deployment settings?|render\.com|web service|static site)",
        flags=re.IGNORECASE,
    )

    def __init__(self, api_key=None, target_language="PTBR", log_func=print, model=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.target_language = target_language.upper()
        self.log = log_func
        if self.target_language != "PTBR":
            raise ValueError("API settings analysis currently supports PTBR only.")
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

    @staticmethod
    def _analysis_text(content: str, extension: str) -> str:
        extension = extension.lower()
        if extension in {".html", ".htm", ".xml"}:
            soup = BeautifulSoup(content, "xml" if extension == ".xml" else "html.parser")
            for tag in soup.find_all(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text("\n", strip=True)
        return content

    @classmethod
    def is_candidate(cls, content: str, extension: str) -> bool:
        return bool(cls.CANDIDATE_PATTERN.search(cls._analysis_text(content, extension)))

    def analyze(self, content: str, extension: str, page_title: str, source_file: str):
        analysis_text = self._analysis_text(content, extension)
        if not self.CANDIDATE_PATTERN.search(analysis_text):
            return []
        if not self.client_ready:
            raise RuntimeError("API settings analysis cannot run because GEMINI_API_KEY is missing.")

        prompt = (
            "You audit software-development course pages for actionable API, deployment, and "
            "external-service configuration settings. Identify settings a translator or course "
            "maintainer must verify in a provider dashboard, configuration file, environment, or "
            "API client. This includes provider choices, service types, branches, build/start "
            "commands, publish directories, endpoints, environment-variable names, authentication "
            "requirements, and similar setup values. Render deployment settings count even when "
            "the page does not call them API settings. Do not report generic conceptual mentions "
            "of an API without an actionable configuration instruction.\n\n"
            "Return ONLY a JSON object with an 'api_settings' array. Each distinct setting must be "
            "one item containing 'provider', 'setting', 'value', and 'context_summary_pt'. Use the "
            "product or service name as provider (for example, Render). Preserve commands, setting "
            "names, environment-variable names, endpoints, filenames, and literal selectable "
            "values exactly as written. Write context_summary_pt in Brazilian Portuguese. NEVER "
            "return an actual password, secret, token, private key, or credential value; report "
            "only its variable/field name and an instruction such as 'copiar do .env'. Return an "
            "empty array when the page has no actionable settings.\n\n"
            f"PAGE TITLE: {page_title}\nSOURCE FILE: {source_file}\nCONTENT:\n{analysis_text}"
        )

        last_error = None
        for attempt in range(3):
            try:
                response = call_gemini_with_retry(self.model, prompt, log_func=self.log)
                payload = self._parse_json(response.text or "")
                settings = payload.get("api_settings")
                if not isinstance(settings, list):
                    raise ValueError("Response has no api_settings array.")

                rows = []
                seen = set()
                for item in settings:
                    provider = str(item.get("provider", "")).strip()
                    setting = str(item.get("setting", "")).strip()
                    value = str(item.get("value", "")).strip()
                    context = str(item.get("context_summary_pt", "")).strip()
                    if not provider or not setting or not context:
                        continue
                    key = (provider.casefold(), setting.casefold(), value.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "page_title": page_title,
                        "source_file": source_file,
                        "provider": provider,
                        "setting": setting,
                        "value": value,
                        "context_summary": context,
                    })
                return rows
            except Exception as error:
                last_error = error
                self.log(
                    f"[APISettingsBot] Attempt {attempt + 1}/3 failed for "
                    f"{source_file}: {error}"
                )
        raise RuntimeError(f"API settings analysis failed for {source_file}: {last_error}")
