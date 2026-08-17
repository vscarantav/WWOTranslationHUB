import os
import json
import re
import html
import time
from bs4 import BeautifulSoup, CData
import google.generativeai as genai  # type: ignore

class XMLTranslationBot:
    def __init__(self, api_key=None, target_language="PTBR", log_lock=None, workspace_dir=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False
            
        self.workspace_dir = workspace_dir
            
        self.target_language = target_language
        self.log_lock = log_lock
        self.model = genai.GenerativeModel(
            "gemini-3.5-flash"
        )
        self.system_prompt = f"You are an expert academic text translator. Translate ALL human-readable text inside each <translate_item> to {self.target_language}. You MUST translate all words, including prefixes, labels, or words wrapped inside inline HTML tags (like <strong>Purpose:</strong> or <b>Task:</b>). Maintain any HTML tags within the strings exactly as they are without translating the tag names themselves. Do not translate URLs or filenames. Return exactly the same XML-like structure with the translated text, ensuring you keep the 'id' attributes intact. Do NOT modify the 'id' attribute."
        
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

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    def _translate_batch(self, batch: dict, constraints: str) -> dict:
        if not self.client_ready:
            return batch
        if not batch:
            return {}

        from bots.api_utils import call_gemini_with_retry
        
        # Construct XML-like payload
        payload = ""
        for k, v in batch.items():
            payload += f'<translate_item id="{k}">{v}</translate_item>\n'
            
        full_prompt = f"System Instructions:\n{self.system_prompt}{constraints}\n\nContent:\n{payload}"
        
        for attempt in range(3):
            try:
                response = call_gemini_with_retry(self.model, full_prompt, log_func=self._log)
                output = response.text.strip() if response.text else ""
                
                # Parse output using BeautifulSoup
                soup_out = BeautifulSoup(output, 'html.parser')
                translated_batch = {}
                
                items = soup_out.find_all('translate_item')
                if not items:
                    raise ValueError("No <translate_item> tags found in the response.")
                    
                for item in items:
                    item_id = item.get('id')
                    if item_id is not None:
                        translated_batch[item_id] = item.decode_contents().strip()
                        
                # Check if we got at least some translations back
                if not translated_batch:
                    raise ValueError("Could not extract any translations.")
                    
                # For any missing keys, fall back to the original
                for k, v in batch.items():
                    if k not in translated_batch:
                        translated_batch[k] = v
                        
                return translated_batch
            except Exception as e:
                msg = f"[XMLBot] XML Parse Error on attempt {attempt+1}: {e}"
                print(msg)
                self._log(msg)
                time.sleep(2)
                
        # If it fails completely, return original English batch so we don't crash
        return batch

    def translate_xml_content(self, xml_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None, page_title: str = "Unknown") -> str:
        if not self.client_ready:
            msg = "[XMLBot] WARNING: No API key provided. Returning original content."
            print(msg)
            self._log(msg)
            return xml_content

        msg = "[XMLBot] Parsing XML safely with BeautifulSoup..."
        self._log(msg)
        
        soup = BeautifulSoup(xml_content, 'xml')
        
        target_tags = ['title', 'mattext', 'description', 'long_description', 'fieldentry', 'text']
        
        strings_to_translate = {}
        tag_references = {}
        is_cdata_map = {}
        
        counter = 0
        for tag in soup.find_all(target_tags):
            if tag.name == 'fieldentry':
                label = tag.find_previous_sibling('fieldlabel')
                if not (label and label.text.strip() == 'bank_title'):
                    continue
                    
            inner_str = tag.decode_contents().strip()
            
            # Prevent Canvas from converting True/False questions to Multiple Choice
            if tag.name == 'mattext' and inner_str in ["True", "False"]:
                continue
                
            if inner_str:
                unescaped = html.unescape(inner_str)
                
                # Check for images if we have an image bot
                if self.image_bot and '<img' in unescaped:
                    inner_soup = BeautifulSoup(unescaped, 'html.parser')
                    img_tags = inner_soup.find_all('img')
                    if img_tags:
                        for img in img_tags:
                            self.image_bot.process_image_tag(img, page_title)
                        unescaped = str(inner_soup)
                        
                strings_to_translate[str(counter)] = unescaped
                tag_references[str(counter)] = ('text', tag, None)
                
                cdata_found = False
                for child in tag.contents:
                    if isinstance(child, CData):
                        cdata_found = True
                        break
                is_cdata_map[str(counter)] = cdata_found
                
                counter += 1
                
        for item in soup.find_all('item'):
            if item.has_attr('title'):
                title_val = item['title'].strip()
                if title_val:
                    unescaped = html.unescape(title_val)
                    strings_to_translate[str(counter)] = unescaped
                    tag_references[str(counter)] = ('attribute', item, 'title')
                    is_cdata_map[str(counter)] = False
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
            
            translated_batch = self._translate_batch(batch, constraints)
            translated_strings.update(translated_batch)
            
        for key, ref in tag_references.items():
            if key in translated_strings:
                trans_text = translated_strings[key]
                # Strict whitespace normalization
                trans_text = trans_text.replace('\u00A0', ' ')
                trans_text = trans_text.replace('&nbsp;', ' ')
                ref_type, tag_node, attr_name = ref
                
                if ref_type == 'attribute':
                    tag_node[attr_name] = trans_text
                else:
                    tag_node.clear()
                    if is_cdata_map.get(key, False):
                        tag_node.append(CData(trans_text))
                    else:
                        tag_node.append(trans_text)
                
        return str(soup)

    def process_file(self, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        msg = f"[XMLBot] Translating {filepath} to {self.target_language}..."
        print(msg)
        self._log(msg)
        
        page_title = os.path.basename(filepath)
        translated_content = self.translate_xml_content(content, page_title=page_title)
        return translated_content
