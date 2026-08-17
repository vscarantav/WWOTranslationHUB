import os
import json
import re
import uuid
from bs4 import BeautifulSoup
import google.generativeai as genai  # type: ignore

class HTMLTranslationBot:
    def __init__(self, api_key=None, target_language="PTBR", log_lock=None, workspace_dir=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False
            
        self.workspace_dir = workspace_dir
            
        self.target_language = target_language
        self.model = genai.GenerativeModel("gemini-3.5-flash")
        self.system_prompt = self._get_system_prompt()
        self.log_lock = log_lock
        
        self.log_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translation_log.txt")
            
        self.image_bot = None
        if self.workspace_dir:
            from bots.image_bot import ImageProcessorBot
            self.image_bot = ImageProcessorBot(self.target_language, self.workspace_dir, self.log_lock, self.log_filepath)

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

    def _get_system_prompt(self):
        return f"You are an expert HTML translator. Translate text into {self.target_language}. Do not modify tags or layout. Output strictly the translated HTML block. Do not translate URLs, UUID placeholders, or internal variable names."

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    def translate_html_content(self, html_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None, page_title: str = "Unknown") -> str:
        if not self.client_ready:
            msg = "[HTMLBot] WARNING: No API key provided. Returning original content."
            print(msg)
            self._log(msg)
            return html_content

        # Protect URLs by swapping them with UUIDs
        soup = BeautifulSoup(html_content, 'html.parser')
        url_map = {}
        
        for tag in soup.find_all(True):
            for attr in ['src', 'href']:
                if tag.has_attr(attr) and tag[attr]:
                    placeholder = f"__URL_{uuid.uuid4().hex}__"
                    url_map[placeholder] = tag[attr]
                    tag[attr] = placeholder
                    
        # Process images
        if self.image_bot:
            for img in soup.find_all('img'):
                self.image_bot.process_image_tag(img, page_title)
                    
        protected_html = str(soup)

        try:
            constraints = ""
            if relevant_glossary:
                constraints += f"\n\nGLOSSARY CONSTRAINTS: You MUST use the following translated terms for these English words:\n{json.dumps(relevant_glossary, indent=2, ensure_ascii=False)}"
            if relevant_scriptures:
                constraints += f"\n\nSCRIPTURE CONSTRAINTS: When translating scriptures, use these exact official translations instead of translating them yourself:\n{json.dumps(relevant_scriptures, indent=2, ensure_ascii=False)}"
                
            full_prompt = f"System Instructions:\n{self.system_prompt}{constraints}\n\nContent to translate:\n{protected_html}"
            from bots.api_utils import call_gemini_with_retry
            response = call_gemini_with_retry(self.model, full_prompt, log_func=self._log)

            raw_content = response.text
            output = raw_content.strip() if raw_content else ""

            match = re.search(r"```html\n(.*?)\n```", output, re.DOTALL)
            if match:
                output = match.group(1).strip()

            # Restore URLs
            for placeholder, original_url in url_map.items():
                output = output.replace(placeholder, original_url)

            # Strict whitespace normalization: replace non-breaking spaces and &nbsp; with regular spaces
            output = output.replace('\u00A0', ' ')
            output = output.replace('&nbsp;', ' ')

            return output
        except Exception as e:
            msg = f"[HTMLBot] Error during translation: {e}"
            print(msg)
            self._log(msg)
            return html_content

    def process_file(self, filepath: str, relevant_glossary: dict = None) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        msg = f"[HTMLBot] Translating {filepath} to {self.target_language}..."
        print(msg)
        self._log(msg)
        
        if len(content) > 30000:
            msg_size = f"[HTMLBot] WARNING: Large file detected ({len(content)} chars). Consider segmenting manually if issues arise."
            print(msg_size)
            self._log(msg_size)

        page_title = os.path.basename(filepath)
        translated_content = self.translate_html_content(content, relevant_glossary=relevant_glossary, page_title=page_title)
        return translated_content
