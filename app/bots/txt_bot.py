import os
import json
import re
import google.generativeai as genai  # type: ignore


class TextTranslationBot:
    @staticmethod
    def _is_unchanged_english_text(source: str, translated: str) -> bool:
        if source.strip().casefold() != translated.strip().casefold():
            return False
        words = re.findall(r"[A-Za-z]+", source.casefold())
        markers = {
            "the", "and", "to", "of", "in", "is", "that", "for", "with",
            "this", "you", "your", "from", "will", "are", "on", "as",
        }
        return len(words) >= 4 and any(word in markers for word in words)

    def __init__(self, api_key=None, target_language="PTBR", log_lock=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False

        self.target_language = target_language
        self.model = genai.GenerativeModel("gemini-3.5-flash")
        self.system_prompt = f"You are an expert academic translator. Translate the given text accurately into {self.target_language}."
        self.log_lock = log_lock
        
        self.log_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translation_log.txt")

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.log_lock:
            with self.log_lock:
                with open(self.log_filepath, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {message}\n")
        else:
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    @staticmethod
    def _chunks(text_content: str, limit: int = 12000) -> list[str]:
        if len(text_content) <= limit:
            return [text_content]
        chunks = []
        current = ""
        for line in text_content.splitlines(keepends=True):
            if current and len(current) + len(line) > limit:
                chunks.append(current)
                current = ""
            if len(line) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(
                    line[index:index + limit]
                    for index in range(0, len(line), limit)
                )
            else:
                current += line
        if current:
            chunks.append(current)
        return chunks or [text_content]

    def translate_txt_content(self, text_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None) -> str:
        if not self.client_ready:
            msg = "[TextBot] ERROR: No Gemini API key provided."
            print(msg)
            self._log(msg)
            raise RuntimeError("Text translation cannot run because no API key is configured.")

        try:
            # We pass the system prompt along with the user content
            # Gemini models prefer system instructions in the model initialization or inline.
            # We'll use a standard prompt structure.
            constraints = ""
            if relevant_glossary:
                constraints += f"\n\nGLOSSARY CONSTRAINTS: You MUST use the following translated terms for these English words:\n{json.dumps(relevant_glossary, indent=2, ensure_ascii=False)}"
            if relevant_scriptures:
                constraints += f"\n\nSCRIPTURE CONSTRAINTS: When translating scriptures, use these exact official translations instead of translating them yourself:\n{json.dumps(relevant_scriptures, indent=2, ensure_ascii=False)}"
                
            from bots.api_utils import call_gemini_with_retry
            chunks = self._chunks(text_content)
            translated_chunks = []
            for index, chunk in enumerate(chunks, start=1):
                full_prompt = (
                    f"System Instructions:\n{self.system_prompt}{constraints}\n\n"
                    f"This is chunk {index} of {len(chunks)}. Translate the complete chunk and "
                    "return only its translated content. Do not summarize or omit anything.\n\n"
                    f"Content to translate:\n{chunk}"
                )
                response = call_gemini_with_retry(self.model, full_prompt, log_func=self._log)
                output = (response.text or "").strip()
                if not output:
                    raise ValueError(f"Gemini returned an empty text chunk ({index}/{len(chunks)}).")
                if self._is_unchanged_english_text(chunk, output):
                    raise ValueError(
                        f"Gemini returned text chunk {index}/{len(chunks)} unchanged in English."
                    )
                leading = chunk[:len(chunk) - len(chunk.lstrip())]
                trailing = chunk[len(chunk.rstrip()):]
                translated_chunks.append(f"{leading}{output}{trailing}")
            result = "".join(translated_chunks)
            # Strict whitespace normalization
            result = result.replace('\u00A0', ' ')
            result = result.replace('&nbsp;', ' ')
            return result
        except Exception as e:
            msg = f"[TextBot] Error during translation: {e}"
            print(msg)
            self._log(msg)
            raise RuntimeError(f"Text translation failed: {e}") from e

    def process_file(self, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        msg = f"[TextBot] Translating {filepath} to {self.target_language} using Gemini..."
        print(msg)
        self._log(msg)
        translated_content = self.translate_txt_content(content)
        return translated_content
