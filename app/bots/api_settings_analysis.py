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
    SENSITIVE_NAME_PATTERN = re.compile(
        r"(?:password|passwd|secret|token|api[_ -]?key|private[_ -]?key|credential)",
        flags=re.IGNORECASE,
    )
    SECRET_ASSIGNMENT_PATTERN = re.compile(
        r"(?P<prefix>\b(?:[A-Za-z_][A-Za-z0-9_.-]*[_.-])?"
        r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)"
        r"[A-Za-z0-9_.-]*(?:\s*[:=]\s*|\s+is\s+))"
        r"(?P<quote>['\"]?)(?P<value>[^\s'\"<>;,]+)(?P=quote)",
        flags=re.IGNORECASE,
    )
    SECRET_VALUE_PATTERNS = (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            flags=re.DOTALL,
        ),
        re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        re.compile(r"(?i)(?:token|api[_-]?key|secret|password)=([^&\s]+)"),
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

    @classmethod
    def _redact_secrets(cls, text: str) -> str:
        """Remove credential values before model submission or report creation."""
        redacted = cls.SECRET_ASSIGNMENT_PATTERN.sub(
            lambda match: f"{match.group('prefix')}[REDACTED]",
            str(text or ""),
        )
        for pattern in cls.SECRET_VALUE_PATTERNS:
            redacted = pattern.sub(
                lambda match: (
                    match.group(0).split("=", 1)[0] + "=[REDACTED]"
                    if "=" in match.group(0)
                    else "[REDACTED]"
                ),
                redacted,
            )
        return redacted

    @classmethod
    def _safe_report_value(cls, setting: str, value: str) -> str:
        value = cls._redact_secrets(value).strip()
        if not value:
            return ""
        if cls.SENSITIVE_NAME_PATTERN.search(setting):
            # Environment-variable and field names are safe metadata, but their
            # assigned values never belong in a translation report.
            if re.fullmatch(r"\$?\{?[A-Z][A-Z0-9_]+\}?", value):
                return value
            return "[REDACTED]"
        if "[REDACTED]" in value:
            return "[REDACTED]"
        return value

    def analyze(self, content: str, extension: str, page_title: str, source_file: str):
        source_analysis_text = self._analysis_text(content, extension)
        if not self.CANDIDATE_PATTERN.search(source_analysis_text):
            return []
        if not self.client_ready:
            raise RuntimeError("API settings analysis cannot run because GEMINI_API_KEY is missing.")

        analysis_text = self._redact_secrets(source_analysis_text)
        safe_page_title = self._redact_secrets(page_title)
        safe_source_file = self._redact_secrets(source_file)
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
            f"PAGE TITLE: {safe_page_title}\nSOURCE FILE: {safe_source_file}\n"
            f"CONTENT:\n{analysis_text}"
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
                    provider = self._redact_secrets(str(item.get("provider", ""))).strip()
                    setting = self._redact_secrets(str(item.get("setting", ""))).strip()
                    value = self._safe_report_value(
                        setting, str(item.get("value", "")).strip()
                    )
                    context = self._redact_secrets(
                        str(item.get("context_summary_pt", ""))
                    ).strip()
                    if not provider or not setting or not context:
                        continue
                    key = (provider.casefold(), setting.casefold(), value.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "page_title": safe_page_title,
                        "source_file": safe_source_file,
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
