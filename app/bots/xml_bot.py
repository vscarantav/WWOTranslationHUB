import os
import json
import re
import html
import time
from bs4 import BeautifulSoup, CData, XMLParsedAsHTMLWarning
import warnings
import google.generativeai as genai  # type: ignore

from core.language_config import language_config, normalize_language_code

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

XML_BATCH_MAX_LINES = 600
XML_BATCH_TARGET_CHARACTERS = 8000


class XMLTranslationBot:
    @staticmethod
    def _is_unchanged_english_text(source: str, translated: str) -> bool:
        source_text = BeautifulSoup(source, "html.parser").get_text(" ", strip=True)
        translated_text = BeautifulSoup(translated, "html.parser").get_text(
            " ", strip=True
        )
        if source_text.casefold() != translated_text.casefold():
            return False
        words = re.findall(r"[A-Za-z]+", source_text.casefold())
        markers = {
            "the", "and", "to", "of", "in", "is", "that", "for", "with",
            "this", "you", "your", "from", "will", "are", "on", "as",
        }
        return len(words) >= 4 and any(word in markers for word in words)

    def __init__(self, api_key=None, target_language="PTBR", log_lock=None, workspace_dir=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False
            
        self.workspace_dir = workspace_dir
            
        self.target_language = normalize_language_code(target_language)
        self.log_lock = log_lock
        self.model = genai.GenerativeModel(
            "gemini-3.5-flash"
        )
        target_name = language_config(self.target_language)["name"]
        self.system_prompt = f"You are an expert academic text translator. Translate ALL human-readable text inside each <translate_item> to {target_name}. You MUST translate all words, including prefixes, labels, or words wrapped inside inline HTML tags (like <strong>Purpose:</strong> or <b>Task:</b>). Maintain any HTML tags within the strings exactly as they are without translating the tag names themselves. Do not translate URLs or filenames. Return exactly the same XML-like structure with the translated text, ensuring you keep the 'id' attributes intact. Do NOT modify the 'id' attribute."
        
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

    @staticmethod
    def _content_line_count(content: str) -> int:
        return max(1, len(content.splitlines()))

    @classmethod
    def _split_items_by_line_limit(cls, items: dict) -> tuple[list[tuple[str, str]], dict[str, list[str]]]:
        split_items = []
        source_chunks = {}

        for source_id, content in items.items():
            lines = content.splitlines()
            if not lines:
                lines = [content]

            chunks = [
                "\n".join(lines[index:index + XML_BATCH_MAX_LINES])
                for index in range(0, len(lines), XML_BATCH_MAX_LINES)
            ]
            if len(chunks) == 1:
                chunk_ids = [source_id]
            else:
                chunk_ids = [
                    f"{source_id}__line_chunk_{index}"
                    for index in range(1, len(chunks) + 1)
                ]

            source_chunks[source_id] = chunk_ids
            split_items.extend(zip(chunk_ids, chunks))

        return split_items, source_chunks

    @classmethod
    def _build_line_limited_batches(cls, items: dict) -> tuple[list[dict], dict[str, list[str]]]:
        split_items, source_chunks = cls._split_items_by_line_limit(items)
        batches = []
        current_batch = {}
        current_line_count = 0
        current_character_count = 0

        for item_id, content in split_items:
            item_line_count = cls._content_line_count(content)
            item_character_count = len(item_id) + len(content) + 10
            exceeds_limit = current_batch and (
                current_line_count + item_line_count > XML_BATCH_MAX_LINES
                or current_character_count + item_character_count
                > XML_BATCH_TARGET_CHARACTERS
            )
            if exceeds_limit:
                batches.append(current_batch)
                current_batch = {}
                current_line_count = 0
                current_character_count = 0

            current_batch[item_id] = content
            current_line_count += item_line_count
            current_character_count += item_character_count

        if current_batch:
            batches.append(current_batch)

        return batches, source_chunks

    @staticmethod
    def _translation_constraints(
        relevant_glossary: dict = None,
        relevant_scriptures: dict = None,
    ) -> str:
        constraints = ""
        if relevant_glossary:
            constraints += (
                "\n\nGLOSSARY CONSTRAINTS: You MUST use the following "
                "translated terms for these English words:\n"
                + json.dumps(relevant_glossary, indent=2, ensure_ascii=False)
            )
        if relevant_scriptures:
            constraints += (
                "\n\nSCRIPTURE CONSTRAINTS: When translating scriptures, use "
                "these exact official translations instead of translating them "
                "yourself:\n"
                + json.dumps(relevant_scriptures, indent=2, ensure_ascii=False)
            )
        return constraints

    def translate_text_items(
        self,
        items: dict[str, str],
        relevant_glossary: dict = None,
        relevant_scriptures: dict = None,
        context_label: str = "XML content",
    ) -> dict[str, str]:
        """Translate keyed text fragments through the configured XML agent."""
        if not self.client_ready:
            self._log("[XMLBot] ERROR: No API key provided.")
            raise RuntimeError(
                "XML translation cannot run because no API key is configured."
            )
        if not items:
            return {}

        constraints = self._translation_constraints(
            relevant_glossary,
            relevant_scriptures,
        )
        self._log(
            f"[XMLBot] Found {len(items)} translatable nodes in {context_label}. "
            f"Processing in batches of at most {XML_BATCH_MAX_LINES} content lines..."
        )

        translated_chunks = {}
        batches, source_chunks = self._build_line_limited_batches(items)
        for index, batch in enumerate(batches, start=1):
            batch_line_count = sum(
                self._content_line_count(content) for content in batch.values()
            )
            self._log(
                f"[XMLBot] Translating batch {index}/{len(batches)} "
                f"({batch_line_count}/{XML_BATCH_MAX_LINES} content lines; "
                f"approx {len(json.dumps(batch))} chars)..."
            )
            translated_chunks.update(self._translate_batch(batch, constraints))

        return {
            source_id: "\n".join(
                translated_chunks[chunk_id] for chunk_id in chunk_ids
            )
            for source_id, chunk_ids in source_chunks.items()
        }

    def _translate_batch(self, batch: dict, constraints: str) -> dict:
        if not self.client_ready:
            raise RuntimeError("XML translation cannot run because no API key is configured.")
        if not batch:
            return {}

        from bots.api_utils import call_gemini_with_retry
        
        # Construct XML-like payload
        payload = ""
        for k, v in batch.items():
            payload += f'<translate_item id="{k}">{v}</translate_item>\n'

        payload_line_count = len(payload.splitlines())
        if payload_line_count > XML_BATCH_MAX_LINES:
            raise ValueError(
                "XML translation payload exceeds the "
                f"{XML_BATCH_MAX_LINES}-line limit: {payload_line_count} lines."
            )
            
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
                        
                # Every requested node must be returned. Partial XML translations
                # are unsafe because they otherwise look like successful files.
                if not translated_batch:
                    raise ValueError("Could not extract any translations.")

                missing_keys = sorted(set(batch) - set(translated_batch))
                if missing_keys:
                    raise ValueError(
                        f"Model omitted {len(missing_keys)} XML node(s): "
                        + ", ".join(missing_keys[:10])
                    )
                unchanged_keys = [
                    key
                    for key, source_text in batch.items()
                    if self._is_unchanged_english_text(
                        source_text, translated_batch.get(key, "")
                    )
                ]
                if unchanged_keys:
                    raise ValueError(
                        "Model left English XML text unchanged for item(s): "
                        + ", ".join(unchanged_keys[:10])
                    )
                        
                return translated_batch
            except Exception as e:
                msg = f"[XMLBot] XML Parse Error on attempt {attempt+1}: {e}"
                self._log(msg)
                time.sleep(2)
                
        raise RuntimeError("Unable to translate XML batch after 3 attempts.")

    def translate_xml_content(self, xml_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None, page_title: str = "Unknown") -> str:
        if not self.client_ready:
            msg = "[XMLBot] ERROR: No API key provided."
            self._log(msg)
            raise RuntimeError("XML translation cannot run because no API key is configured.")

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
                
        for titled_node in soup.find_all(['item', 'assessment', 'objectbank']):
            if titled_node.has_attr('title'):
                title_val = titled_node['title'].strip()
                if title_val:
                    unescaped = html.unescape(title_val)
                    strings_to_translate[str(counter)] = unescaped
                    tag_references[str(counter)] = ('attribute', titled_node, 'title')
                    is_cdata_map[str(counter)] = False
                    counter += 1
                
        if not strings_to_translate:
            return str(soup)
            
        translated_strings = self.translate_text_items(
            strings_to_translate,
            relevant_glossary,
            relevant_scriptures,
            context_label=page_title,
        )
            
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
        self._log(msg)
        
        page_title = os.path.basename(filepath)
        translated_content = self.translate_xml_content(content, page_title=page_title)
        return translated_content
