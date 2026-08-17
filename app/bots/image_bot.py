import os
import mimetypes
import urllib.request
import urllib.parse
import google.generativeai as genai
from bots.api_utils import call_gemini_with_retry

class ImageProcessorBot:
    def __init__(self, target_language: str, workspace_dir: str, log_lock=None, log_filepath=None):
        self.target_language = target_language
        self.workspace_dir = workspace_dir
        self.log_lock = log_lock
        self.log_filepath = log_filepath or os.path.join(os.path.dirname(os.path.abspath(__file__)), "translation_log.txt")
        
        # Use gemini-1.5-flash for both text translation and multimodal generation as it is fast and cost-effective
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        
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
                
    def get_image_bytes(self, src: str) -> tuple[bytes, str]:
        if src.startswith('http://') or src.startswith('https://'):
            req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                img_bytes = response.read()
                mime_type = response.info().get_content_type()
                if not mime_type or not mime_type.startswith('image/'):
                    mime_type, _ = mimetypes.guess_type(src)
                return img_bytes, mime_type or 'image/jpeg'
                
        local_path = src
        if src.startswith('$IMS-CC-FILEBASE$/'):
            local_path = src.replace('$IMS-CC-FILEBASE$/', '')
        elif src.startswith('%24IMS-CC-FILEBASE%24/'):
            local_path = src.replace('%24IMS-CC-FILEBASE%24/', '')
            
        local_path = urllib.parse.unquote(local_path)
            
        if self.workspace_dir:
            full_path = os.path.join(self.workspace_dir, local_path)
            if os.path.exists(full_path):
                with open(full_path, "rb") as f:
                    img_bytes = f.read()
                mime_type, _ = mimetypes.guess_type(full_path)
                return img_bytes, mime_type or 'image/jpeg'
            
        raise FileNotFoundError(f"Image not found locally or remotely: {src}")

    def process_image_tag(self, img_tag, page_title: str):
        """
        Modifies the img_tag in-place.
        """
        alt = img_tag.get('alt', '').strip()
        src = img_tag.get('src', '').strip()
        
        if not src:
            return
            
        if alt:
            prompt = f"Translate the following image alt text to {self.target_language}. Return only the translated text, no quotes or additional formatting:\n{alt}"
            try:
                response = call_gemini_with_retry(self.model, prompt, log_func=self._log)
                if response and response.text:
                    img_tag['alt'] = response.text.strip()
            except Exception as e:
                self._log(f"[ImageBot] Error translating alt text: {e}")
        else:
            self._log(f"[ImageBot] MissingAltText: {page_title},{src}")
            try:
                img_bytes, mime_type = self.get_image_bytes(src)
                prompt_text = f"Describe this image concisely for an alt text attribute in {self.target_language}. Return only the description, without quotes."
                
                parts = [
                    {"mime_type": mime_type, "data": img_bytes},
                    prompt_text
                ]
                
                response = call_gemini_with_retry(self.model, parts, log_func=self._log)
                if response and response.text:
                    img_tag['alt'] = response.text.strip()
            except Exception as e:
                self._log(f"[ImageBot] Error generating alt text for {src}: {e}")
