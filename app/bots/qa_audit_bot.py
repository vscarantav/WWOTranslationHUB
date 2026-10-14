import os
import google.generativeai as genai # type: ignore
from bots.api_utils import call_gemini_with_retry

class QAAuditBot:
    LANGUAGE_NAMES = {"PTBR": "Portuguese", "SPA": "Spanish"}

    def __init__(
        self,
        api_key=None,
        model_name="gemini-3.5-flash",
        target_language="PTBR",
        model=None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.target_language = target_language.upper()
        if self.target_language not in self.LANGUAGE_NAMES:
            raise ValueError("QA auditing supports PTBR or SPA.")
        self.language_name = self.LANGUAGE_NAMES[self.target_language]
        self.translated_column = f"{self.language_name} (Translated)"
        if self.api_key:
            genai.configure(api_key=self.api_key)
        self.client_ready = bool(self.api_key or model)
        self.model = model or genai.GenerativeModel(model_name)
        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.hub_dir = os.path.dirname(self.app_dir)
        
        self.log_filepath = os.path.join(self.app_dir, "bots", "translation_log.txt")
            
        self.system_prompt = self._get_system_prompt()

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def _get_system_prompt(self):
        return f"""# Role and Objective
You are an expert Localization Quality Assurance (QA) Specialist for BYU-Idaho Canvas courses. Your objective is to compare an original English Canvas page (the "Canon") with its {self.language_name} translation. You must identify any discrepancies between the two versions and document them in a clear, structured format.

# Context
- The English text is the absolute source of truth. 
- The {self.language_name} text is supposed to be a direct, accurate, and structurally identical translation of the English text.
- Both texts may contain formatting, hyperlinks, or structural elements (like bullet points or headers) that must also align.

# Core Instructions
1. Carefully read and compare the English (Canon) text against the {self.language_name} (Translated) text section by section, paragraph by paragraph.
2. Evaluate both the textual meaning and the structural flow.
3. Identify any discrepancies where the {self.language_name} version deviates from the English version.
4. Categorize every identified discrepancy using ONLY the predefined categories listed below.
5. Output your findings as a structured table. Do not attempt to fix or rewrite the text; only report the discrepancies.

# Discrepancy Categories
When you find a discrepancy, classify it strictly into one of the following four categories:
* Missing: Content, formatting, links, or sections that exist in the English version but are absent in the {self.language_name} version.
* Extra: Content, formatting, links, or sections that exist in the {self.language_name} version but are nowhere to be found in the English version.
* Different Content: Content that is present in both, but the {self.language_name} version changes the core meaning, contains a severe mistranslation, has different numbers/dates, or features mismatched hyperlinks/URLs.
* Different Order: Content that is correctly translated but appears in a different sequence or structural placement compared to the English version.

# Output Format
For each Excel Report, Present your analysis in a structured Markdown table with the following columns:
1. Location / Element: A brief description of where the issue is (e.g., "Paragraph 2", "List Item 3", "Header 2").
2. English (Canon): The original English text (or a snippet of it) for reference.
3. {self.translated_column}: The current {self.language_name} text (or a snippet of it). Leave blank if "Missing".
4. Discrepancy Type: Must strictly be one of [Missing, Extra, Different Content, Different Order].
5. Description: A brief, clear explanation of exactly what the discrepancy is.

If no discrepancies are found, output: "Comparison complete: The {self.language_name} translation perfectly matches the English canon."
"""

    def audit_content(self, english_content: str, translated_content: str) -> list:
        if not self.client_ready:
            self._log("[QAAuditBot] WARNING: No API key provided.")
            raise RuntimeError("QA audit cannot run because no API key is configured.")

        prompt = f"{self.system_prompt}\n\nEnglish (Canon):\n```\n{english_content}\n```\n\n{self.translated_column}:\n```\n{translated_content}\n```"
        
        try:
            response = call_gemini_with_retry(self.model, prompt, log_func=self._log)
            if response and response.text:
                return self._parse_markdown_table(response.text)
            raise RuntimeError("QA model returned an empty response.")
        except Exception as e:
            self._log(f"[QAAuditBot] Error during LLM audit: {e}")
            raise RuntimeError(f"QA content audit failed: {e}") from e

    def _parse_markdown_table(self, markdown_text: str) -> list:
        if "Comparison complete:" in markdown_text:
            return []
            
        results = []
        lines = markdown_text.strip().split('\n')
        table_started = False
        
        for line in lines:
            line = line.strip()
            if not line.startswith('|'):
                continue
                
            if 'Location / Element' in line and 'Discrepancy Type' in line:
                table_started = True
                continue
                
            if table_started and '---' in line:
                continue
                
            if table_started:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 6:
                    # Columns are English canon, the configured target language,
                    # discrepancy type, and description.
                    results.append({
                        "Location / Element": parts[1],
                        "English (Canon)": parts[2],
                        self.translated_column: parts[3],
                        "Discrepancy Type": parts[4],
                        "Description": parts[5]
                    })
                        
        return results

    def pair_unmatched_files(self, en_titles_dict: dict, pt_titles_dict: dict) -> dict:
        if not self.client_ready:
            return {}
            
        if not en_titles_dict or not pt_titles_dict:
            return {}

        prompt = f"""You are an intelligent mapping assistant. You are given two lists of unmatched Canvas files: one in English and one translated to {self.language_name}.
The translated version may have localized numbers, abbreviations, and titles.
Your job is to match the English file paths to the {self.language_name} file paths based on their titles and filenames.

English Files (Format: "file_path": "Title"):
{en_titles_dict}

{self.language_name} Files (Format: "file_path": "Title"):
{pt_titles_dict}

Return a valid JSON object mapping the English file path keys to their corresponding {self.language_name} file path keys.
ONLY output the raw JSON object, no markdown blocks, no other text.
If an English file has no logical match, omit it.
"""
        try:
            response = call_gemini_with_retry(self.model, prompt, log_func=self._log)
            if response and response.text:
                text = response.text.replace('```json', '').replace('```', '').strip()
                import json
                return json.loads(text)
        except Exception as e:
            self._log(f"[QAAuditBot] Error pairing unmatched files: {e}")
            
        return {}
