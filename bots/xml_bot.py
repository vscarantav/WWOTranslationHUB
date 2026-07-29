import os
import json
import re
import html
import time
from bs4 import BeautifulSoup, CData
import google.generativeai as genai  # type: ignore

class XMLTranslationBot:
    def __init__(self, api_key=None, target_language="PTBR"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False
            
        self.target_language = target_language
        self.model = genai.GenerativeModel(
            "gemini-3.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        self.system_prompt = f"You are an expert academic text translator. Translate the given JSON string values to {self.target_language}. Maintain any HTML tags within the strings exactly as they are. Do not translate URLs or filenames. Return a JSON object with the exact same keys."
        
        self.log_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New XMLBot Session (Target: {self.target_language}) ---\n")

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def set_system_prompt(self, prompt: str):
        pass

    def _translate_json_batch(self, batch: dict, constraints: str) -> dict:
        if not self.client_ready:
            return batch
        if not batch:
            return {}

        from bots.api_utils import call_gemini_with_retry
        
        # Proper newlines in f-string
        full_prompt = f"System Instructions:\n{self.system_prompt}{constraints}\n\nContent:\n{json.dumps(batch, ensure_ascii=False)}"
        
        for attempt in range(3):
            try:
                response = call_gemini_with_retry(self.model, full_prompt, log_func=self._log)
                output = response.text.strip() if response.text else "{}"
                
                # Try parsing exactly as returned
                try:
                    return json.loads(output)
                except json.JSONDecodeError:
                    pass
                    
                # Try extracting from markdown code blocks
                match = re.search(r"```(?:json)?\n?(.*?)\n?```", output, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1).strip())
                    except json.JSONDecodeError:
                        pass
                
                # Fallback: Extract everything between the first '{' and last '}'
                start = output.find('{')
                end = output.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        return json.loads(output[start:end+1])
                    except json.JSONDecodeError:
                        pass
                        
                # If all fail, let it raise the error to trigger the retry loop
                return json.loads(output)
            except Exception as e:
                msg = f"[XMLBot] JSON Error on attempt {attempt+1}: {e}"
                print(msg)
                self._log(msg)
                time.sleep(2)
                
        # If it fails completely, return original English batch so we don't crash
        return batch

    def translate_xml_content(self, xml_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None) -> str:
        msg = "[XMLBot] Parsing XML safely with BeautifulSoup..."
        self._log(msg)
        
        soup = BeautifulSoup(xml_content, 'xml')
        
        question_trans = "Pergunta" if self.target_language == "PTBR" else "Pregunta"
        for item in soup.find_all('item'):
            if item.has_attr('title'):
                item['title'] = re.sub(r'(?i)Question', question_trans, item['title'])
        
        target_tags = ['title', 'mattext', 'description']
        
        strings_to_translate = {}
        tag_references = {}
        is_cdata_map = {}
        
        counter = 0
        for tag in soup.find_all(target_tags):
            inner_str = tag.decode_contents().strip()
            if inner_str:
                unescaped = html.unescape(inner_str)
                strings_to_translate[str(counter)] = unescaped
                tag_references[str(counter)] = tag
                
                cdata_found = False
                for child in tag.contents:
                    if isinstance(child, CData):
                        cdata_found = True
                        break
                is_cdata_map[str(counter)] = cdata_found
                
                counter += 1
                
        if not strings_to_translate:
            return str(soup)
            
        constraints = ""
        if relevant_glossary:
            constraints += f"\n\nGLOSSARY CONSTRAINTS: You MUST use the following translated terms for these English words:\n{json.dumps(relevant_glossary, indent=2, ensure_ascii=False)}"
        if relevant_scriptures:
            constraints += f"\n\nSCRIPTURE CONSTRAINTS: When translating scriptures, use these exact official translations instead of translating them yourself:\n{json.dumps(relevant_scriptures, indent=2, ensure_ascii=False)}"

        msg = f"[XMLBot] Found {len(strings_to_translate)} translatable nodes. Processing via character-based JSON batches..."
        print(msg)
        self._log(msg)
        
        translated_strings = {}
        
        items = list(strings_to_translate.items())
        
        current_batch = {}
        current_batch_size = 0
        batch_limit = 8000 # Character limit
        
        batches = []
        for k, v in items:
            item_size = len(k) + len(v) + 10
            if current_batch_size + item_size > batch_limit and current_batch:
                batches.append(current_batch)
                current_batch = {}
                current_batch_size = 0
                
            current_batch[k] = v
            current_batch_size += item_size
            
        if current_batch:
            batches.append(current_batch)
            
        for i, batch in enumerate(batches):
            msg = f"[XMLBot] Translating batch {i + 1}/{len(batches)} (approx {len(json.dumps(batch))} chars)..."
            self._log(msg)
            
            translated_batch = self._translate_json_batch(batch, constraints)
            translated_strings.update(translated_batch)
            
        for key, tag in tag_references.items():
            if key in translated_strings:
                trans_text = translated_strings[key]
                tag.clear()
                
                if is_cdata_map[key]:
                    tag.append(CData(trans_text))
                else:
                    tag.append(trans_text)
                
        return str(soup)

    def process_file(self, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        msg = f"[XMLBot] Translating {filepath} to {self.target_language}..."
        print(msg)
        self._log(msg)
        translated_content = self.translate_xml_content(content)
        return translated_content
