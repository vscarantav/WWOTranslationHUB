import os
import json
import urllib.parse
import html
import re
from tqdm import tqdm

class LinkProcessor:
    def __init__(self, target_language: str, app_dir: str, filepaths: list, link_prompt_callback=None):
        self.target_language = target_language
        self.app_dir = app_dir
        self.filepaths = filepaths
        self.link_prompt_callback = link_prompt_callback

    def clean_google_links(self, content: str, filepath: str, _log_func) -> str:
        filename = os.path.basename(filepath)
        
        def replacer(match):
            url = match.group(0)
            is_escaped = '&amp;' in url
            unescaped_url = html.unescape(url)
            
            parsed = urllib.parse.urlparse(unescaped_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'q' in qs:
                clean_url = qs['q'][0]
                final_url = html.escape(clean_url) if is_escaped else clean_url
                _log_func(f"[LinkBot] GoogleLinkStripped: {filename},{url},{final_url}")
                return final_url
            return url
            
        return re.sub(r'https?://(?:www\.)?google\.com/url\?[^\s"\'<>]*', replacer, content)

    def rewrite_church_links(self, content: str) -> str:
        lang_code = "por" if self.target_language == "PTBR" else ("spa" if self.target_language == "ES" else "por")
        
        def replacer(match):
            url = match.group(0)
            if 'lang=' in url:
                url = re.sub(r'lang=[a-zA-Z]+', f'lang={lang_code}', url)
            else:
                sep = '&' if '?' in url else '?'
                url = f"{url}{sep}lang={lang_code}"
            return url
            
        return re.sub(r'https?://(?:www\.)?churchofjesuschrist\.org[^\s"\'<>]*', replacer, content)

    def pre_process_links(self, _log_func):
        msg = "Starting Phase 1: Pre-processing and Mapping Links"
        print(f"\n[LinkProcessor] {msg}")
        _log_func(msg)
        
        mapping_file = os.path.join(self.app_dir, "link_mapping.json")
        mapping = {}
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
                
        def save_mapping():
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, indent=2)
        
        session_skipped_urls = set()

        def check_and_prompt(url, filepath, page_title=None):
            is_escaped = '&amp;' in url or '&#39;' in url or '&quot;' in url
            unescaped_url = html.unescape(url)
            clean_url = unescaped_url
            display_name = page_title if page_title else os.path.basename(filepath)
            
            # Ignore standard XML namespaces and Canvas backend links
            ignore_domains = ['w3.org', 'purl.org', 'imsglobal.org', 'canvas.instructure.com', 'ieee.org', 'instructure.com/api/', 'byui-lti-to-url.azurewebsites.net', 'googleusercontent.com', 'instructure.com/assessment_questions/']
            if any(domain in clean_url for domain in ignore_domains):
                return url
                
            # Ignore any internal Canvas file links (images, documents, etc.)
            if 'instructure.com' in clean_url and '/files/' in clean_url:
                return url
            
            # Normalize Google Docs/Drive links by removing /u/<number>/
            if 'google.com' in clean_url:
                clean_url = re.sub(r'/u/\d+/', '/', clean_url)
            
            if 'google.com/url?' in unescaped_url:
                parsed = urllib.parse.urlparse(unescaped_url)
                qs = urllib.parse.parse_qs(parsed.query)
                if 'q' in qs:
                    clean_url = qs['q'][0]
                    if 'google.com' in clean_url:
                        clean_url = re.sub(r'/u/\d+/', '/', clean_url)
                    _log_func(f"[LinkBot] GoogleLinkStripped: {display_name},{url},{clean_url}")
                    
            if clean_url.startswith('https://www.churchofjesuschrist.org/study/scriptures'):
                if 'lang=eng' in clean_url:
                    lang_code = 'por' if self.target_language == 'PTBR' else 'spa'
                    localized_url = clean_url.replace('lang=eng', f'lang={lang_code}')
                    return html.escape(localized_url) if is_escaped else localized_url
                else:
                    return url

            if clean_url in mapping and mapping[clean_url].get(self.target_language):
                pt_link = mapping[clean_url][self.target_language]
                return html.escape(pt_link) if is_escaped else pt_link
                
            # Check if this URL is already a translated value
            for translations in mapping.values():
                if clean_url in translations.values():
                    return url
                
            if not clean_url.startswith('http'):
                return url
                
            if clean_url in session_skipped_urls:
                return url
                
            if self.link_prompt_callback:
                prompt_result = self.link_prompt_callback(clean_url, display_name)
                pt_link = None
                comment = ""
                if isinstance(prompt_result, tuple):
                    pt_link, comment = prompt_result
                else:
                    pt_link = prompt_result
                    
                if pt_link:
                    pt_link = pt_link.strip()
                    pt_link = html.unescape(pt_link)
                    
                    if 'google.com' in pt_link:
                        pt_link = re.sub(r'/u/\d+/', '/', pt_link)
                        
                    if clean_url not in mapping:
                        mapping[clean_url] = {"PTBR": "", "SPA": ""}
                    mapping[clean_url][self.target_language] = pt_link
                    save_mapping()
                    
                    if comment:
                        _log_func(f"[LinkBot] CommentedLink: {display_name},{clean_url},{comment}")
                    
                    return html.escape(pt_link) if is_escaped else pt_link
                else:
                    session_skipped_urls.add(clean_url)
                    if comment:
                        _log_func(f"[LinkBot] SkippedLinkWithComment: {display_name},{clean_url},{comment}")
                    else:
                        _log_func(f"[LinkBot] SkippedLink: {display_name},{clean_url}")
            
            return url

        for filepath in tqdm(self.filepaths, desc="Mapping Links", unit="file"):
            ext = filepath.split('.')[-1].lower() if '.' in filepath else ''
            
            if ext in ['html', 'htm', 'xml', 'qti']:
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    page_title = os.path.basename(filepath)
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
                    if title_match and title_match.group(1).strip():
                        page_title = f"{title_match.group(1).strip()} ({os.path.basename(filepath)})"
                    else:
                        qti_match = re.search(r'<assessment[^>]*title=[\'"]([^\'"]+)[\'"]', content, re.IGNORECASE)
                        if qti_match and qti_match.group(1).strip():
                            page_title = f"{qti_match.group(1).strip()} ({os.path.basename(filepath)})"

                    def html_replacer(match):
                        return f'href={match.group(1)}{check_and_prompt(match.group(2), filepath, page_title)}{match.group(1)}'
                        
                    new_content = re.sub(r'href=(["\'])([^"\']+)\1', html_replacer, content)
                    
                    if ext == 'xml' or ext == 'qti':
                        def xml_url_replacer(match):
                            return f'<url>{check_and_prompt(match.group(1), filepath, page_title)}</url>'
                        new_content = re.sub(r'<url>([^<]+)</url>', xml_url_replacer, new_content)
                    
                    def universal_replacer(match):
                        return check_and_prompt(match.group(0), filepath, page_title)
                    new_content = re.sub(r'https?://[^\s"\'<>]+', universal_replacer, new_content)
                    
                    if new_content != content:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                except Exception as e:
                    print(f"[LinkProcessor] Error processing links in {filepath}: {e}")
                    
            elif ext == 'txt':
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    def txt_replacer(match):
                        return check_and_prompt(match.group(0), filepath)
                        
                    new_content = re.sub(r'https?://[^\s"\'<>]+', txt_replacer, content)
                    
                    if new_content != content:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                except Exception as e:
                    print(f"[LinkProcessor] Error processing txt links in {filepath}: {e}")
