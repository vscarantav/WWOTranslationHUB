import os
import json
import re
import uuid
import html as html_lib
from bs4 import BeautifulSoup, Comment, NavigableString
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

    @staticmethod
    def _is_unchanged_english_text(source_text: str, translated_text: str) -> bool:
        if source_text.strip().casefold() != translated_text.strip().casefold():
            return False
        stripped_source = source_text.strip()
        if re.match(r"^(?:https?://|www\.)\S+$", stripped_source, flags=re.IGNORECASE):
            return False
        if re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", stripped_source):
            return False
        words = re.findall(r"[A-Za-z]+", source_text.casefold())
        english_markers = {
            "the", "and", "to", "of", "in", "is", "that", "for", "with",
            "this", "you", "your", "from", "will", "are", "on", "as",
        }
        return len(words) >= 4 and any(word in english_markers for word in words)

    def _translate_text_batch(self, batch: dict, constraints: str) -> dict:
        """Translate isolated visible-text nodes while retaining stable IDs."""
        if not batch:
            return {}

        from bots.api_utils import call_gemini_with_retry

        payload = "".join(
            f'<translate_item id="{item_id}">{html_lib.escape(text, quote=False)}</translate_item>\n'
            for item_id, text in batch.items()
        )
        prompt = (
            f"System Instructions:\n{self.system_prompt}{constraints}\n\n"
            "Translate the complete text of every translate_item. Return every item with "
            "the same id. Do not omit, merge, or reorder items.\n\n"
            f"Content:\n{payload}"
        )

        last_error = None
        for attempt in range(3):
            try:
                response = call_gemini_with_retry(self.model, prompt, log_func=self._log)
                output = response.text.strip() if response.text else ""
                soup_out = BeautifulSoup(output, "html.parser")
                translated = {}
                for item in soup_out.find_all("translate_item"):
                    item_id = item.get("id")
                    if item_id is not None:
                        translated[item_id] = item.get_text()

                missing_ids = set(batch) - set(translated)
                if missing_ids:
                    raise ValueError(f"Model omitted {len(missing_ids)} text node(s).")

                unchanged_english_ids = [
                    item_id
                    for item_id, source_text in batch.items()
                    if self._is_unchanged_english_text(
                        source_text,
                        translated.get(item_id, ""),
                    )
                ]
                if unchanged_english_ids:
                    unchanged_details = "; ".join(
                        f"{item_id}={batch[item_id][:160]!r}"
                        for item_id in unchanged_english_ids
                    )
                    raise ValueError(
                        "Model left English text unchanged for item(s): "
                        + unchanged_details
                    )
                return translated
            except Exception as exc:
                last_error = exc
                self._log(f"[HTMLBot] Text-batch error on attempt {attempt + 1}: {exc}")

        raise RuntimeError(f"Unable to translate HTML text batch after 3 attempts: {last_error}")

    @staticmethod
    def _translated_boundary_whitespace(
        original_whitespace: str,
        translated_text: str,
        *,
        leading: bool,
    ) -> str:
        """Preserve semantic word separation without relying on HTML newlines."""
        if not original_whitespace:
            return ""
        if leading and re.match(r"^[,.;:!?%…\)\]\}]", translated_text):
            return ""
        return " "

    def translate_html_content_in_chunks(
        self,
        html_content: str,
        relevant_glossary: dict = None,
        relevant_scriptures: dict = None,
        page_title: str = "Unknown",
        batch_limit: int = 6000,
    ) -> str:
        """Translate visible HTML text nodes in bounded batches for large pages."""
        if not self.client_ready:
            raise RuntimeError("HTML translation cannot run because no API key is configured.")

        soup = BeautifulSoup(html_content, "html.parser")

        if self.image_bot:
            for img in soup.find_all("img"):
                self.image_bot.process_image_tag(img, page_title)

        strings_to_translate = {}
        node_references = {}
        ignored_parents = {"script", "style", "code", "pre", "noscript"}

        for node in soup.find_all(string=True):
            if isinstance(node, Comment):
                if node.strip().casefold() in {"startfragment", "endfragment"}:
                    node.extract()
                continue
            if not isinstance(node, NavigableString):
                continue
            if node.parent and node.parent.name in ignored_parents:
                continue

            raw_text = str(node)
            stripped_text = raw_text.strip()
            if not stripped_text or not re.search(r"[A-Za-z]", stripped_text):
                continue

            item_id = str(len(strings_to_translate))
            leading_whitespace = raw_text[:len(raw_text) - len(raw_text.lstrip())]
            trailing_whitespace = raw_text[len(raw_text.rstrip()):]
            strings_to_translate[item_id] = stripped_text
            node_references[item_id] = (node, leading_whitespace, trailing_whitespace)

        if not strings_to_translate:
            raise RuntimeError("No visible text nodes were found on the HTML page.")

        constraints = ""
        if relevant_glossary:
            constraints += (
                "\n\nGLOSSARY CONSTRAINTS: You MUST use the following translated terms "
                "for these English words:\n"
                f"{json.dumps(relevant_glossary, indent=2, ensure_ascii=False)}"
            )
        if relevant_scriptures:
            constraints += (
                "\n\nSCRIPTURE CONSTRAINTS: Use these exact official translations:\n"
                f"{json.dumps(relevant_scriptures, indent=2, ensure_ascii=False)}"
            )

        batches = []
        current_batch = {}
        current_size = 0
        for item_id, text in strings_to_translate.items():
            item_size = len(item_id) + len(text) + 40
            if current_batch and current_size + item_size > batch_limit:
                batches.append(current_batch)
                current_batch = {}
                current_size = 0
            current_batch[item_id] = text
            current_size += item_size
        if current_batch:
            batches.append(current_batch)

        self._log(
            f"[HTMLBot] Translating {len(strings_to_translate)} visible text nodes "
            f"in {len(batches)} batch(es) for {page_title}."
        )

        translated_strings = {}
        for index, batch in enumerate(batches, start=1):
            self._log(f"[HTMLBot] Translating text batch {index}/{len(batches)} for {page_title}.")
            translated_strings.update(self._translate_text_batch(batch, constraints))

        changed_count = 0
        for item_id, original_text in strings_to_translate.items():
            translated_text = translated_strings[item_id].strip()
            if not translated_text:
                raise RuntimeError(f"Translation returned an empty text node for item {item_id}.")
            if translated_text.casefold() != original_text.casefold():
                changed_count += 1

            node, leading_whitespace, trailing_whitespace = node_references[item_id]
            leading_whitespace = self._translated_boundary_whitespace(
                leading_whitespace,
                translated_text,
                leading=True,
            )
            trailing_whitespace = self._translated_boundary_whitespace(
                trailing_whitespace,
                translated_text,
                leading=False,
            )
            node.replace_with(NavigableString(
                f"{leading_whitespace}{translated_text}{trailing_whitespace}"
            ))

        if changed_count == 0:
            raise RuntimeError("The model returned the HTML page unchanged in English.")

        self._log(
            f"[HTMLBot] Changed {changed_count}/{len(strings_to_translate)} visible text nodes "
            f"for {page_title}."
        )
        return str(soup)

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

            # Strip markdown wrappers if present
            output = re.sub(r"^```html\s*?\n", "", output, flags=re.IGNORECASE)
            output = re.sub(r"\n```\s*?$", "", output)
            output = output.strip()

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
