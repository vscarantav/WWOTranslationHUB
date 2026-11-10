"""Canonical target-language metadata shared across Translation Hub flows."""


LANGUAGES = {
    "PTBR": {
        "name": "Portuguese (Brazil)",
        "ui_label": "Portuguese (PTBR)",
        "canvas_language": "Português",
        "church_code": "por",
        "html_language": "pt-BR",
        "scripture_folder": "por",
        "report_suffix": "PT",
        "book_label": "PT",
    },
    "SPA": {
        "name": "Spanish",
        "ui_label": "Spanish (SPA)",
        "canvas_language": "Spanish",
        "church_code": "spa",
        "html_language": "es",
        "scripture_folder": "spa",
        "report_suffix": "SPA",
        "book_label": "Spanish",
    },
    "FRA": {
        "name": "French",
        "ui_label": "French (FRA)",
        "canvas_language": "Français",
        "church_code": "fra",
        "html_language": "fr",
        "scripture_folder": "fra",
        "report_suffix": "FRA",
        "book_label": "French",
    },
}

SUPPORTED_TARGET_LANGUAGES = tuple(LANGUAGES)


def normalize_language_code(value):
    """Return a supported uppercase language code or raise a useful error."""
    code = str(value or "").strip().upper()
    if code not in LANGUAGES:
        supported = ", ".join(SUPPORTED_TARGET_LANGUAGES)
        raise ValueError(f"Unsupported target language {value!r}. Choose one of: {supported}.")
    return code


def language_config(value):
    """Return canonical metadata for one supported target language."""
    return LANGUAGES[normalize_language_code(value)]
