import os
import json
import google.generativeai as genai  # type: ignore


class TextTranslationBot:
    def __init__(self, api_key=None, target_language="PTBR"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False

        self.target_language = target_language
        self.model = genai.GenerativeModel("gemini-3.5-flash")
        self.system_prompt = f"You are an expert academic translator. Translate the given text accurately into {self.target_language}."
        
        self.log_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New TextBot Session (Target: {self.target_language}) ---\n")

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    def translate_txt_content(self, text_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None) -> str:
        if not self.client_ready:
            msg = "[TextBot] WARNING: No Gemini API key provided. Returning original content."
            print(msg)
            self._log(msg)
            return text_content

        try:
            # We pass the system prompt along with the user content
            # Gemini models prefer system instructions in the model initialization or inline.
            # We'll use a standard prompt structure.
            constraints = ""
            if relevant_glossary:
                constraints += f"\n\nGLOSSARY CONSTRAINTS: You MUST use the following translated terms for these English words:\n{json.dumps(relevant_glossary, indent=2, ensure_ascii=False)}"
            if relevant_scriptures:
                constraints += f"\n\nSCRIPTURE CONSTRAINTS: When translating scriptures, use these exact official translations instead of translating them yourself:\n{json.dumps(relevant_scriptures, indent=2, ensure_ascii=False)}"
                
            full_prompt = f"System Instructions:\n{self.system_prompt}{constraints}\n\nContent to translate:\n{text_content}"
            from bots.api_utils import call_gemini_with_retry
            response = call_gemini_with_retry(self.model, full_prompt, log_func=self._log)
            return response.text.strip()
        except Exception as e:
            msg = f"[TextBot] Error during translation: {e}"
            print(msg)
            self._log(msg)
            return text_content

    def process_file(self, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        msg = f"[TextBot] Translating {filepath} to {self.target_language} using Gemini..."
        print(msg)
        self._log(msg)
        translated_content = self.translate_txt_content(content)
        return translated_content
