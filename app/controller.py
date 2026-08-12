import os
import collections
from tqdm import tqdm
import json
import argparse
import shutil
import concurrent.futures
import re
import zipfile
import pandas as pd
from datetime import datetime
import xlsxwriter
from dotenv import load_dotenv
from bs4 import BeautifulSoup
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)
from bots.html_bot import HTMLTranslationBot
from bots.xml_bot import XMLTranslationBot
from bots.txt_bot import TextTranslationBot
from bots.auditor_bot import GlossaryAuditBot
from bots.scripturecheck_bot import ScriptureCheckBot

class TranslationController:
    def __init__(self, target_language="PTBR", input_dir=None, imscc_path=None, link_prompt_callback=None):
        self.target_language = target_language
        self.link_prompt_callback = link_prompt_callback
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.hub_dir = os.path.dirname(self.app_dir)
        self._clear_logs()
        self.input_dir = input_dir
        self.imscc_path = imscc_path
        self.instructions = self._load_instructions()
        self.auditor = GlossaryAuditBot(target_language=self.target_language, hub_dir=self.hub_dir)
        self.scripture_checker = ScriptureCheckBot(target_language=self.target_language, hub_dir=self.hub_dir)
        
        # Initialize specialized bots
        self.bots = {
            "html": HTMLTranslationBot(target_language=self.target_language),
            "xml": XMLTranslationBot(target_language=self.target_language),
            "qti": XMLTranslationBot(target_language=self.target_language), # QTI uses XML bot for now
            "txt": TextTranslationBot(target_language=self.target_language)
        }
        
        # Apply prompts if available in instructions
        self._apply_custom_prompts()
        self.log_filepath = os.path.join(self.app_dir, "bots", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New Session (Target: {self.target_language}) ---\n")
            
        self._setup_workspace()

    def _clear_logs(self):
        log_files = [
            "translation_log.txt",
            "html_bot_log.txt",
            "xml_bot_log.txt",
            "txt_bot_log.txt",
            "auditor_bot_log.txt",
            "scripture_bot_log.txt"
        ]
        for log_file in log_files:
            log_path = os.path.join(self.app_dir, "bots", log_file)
            if os.path.exists(log_path):
                try:
                    os.remove(log_path)
                except Exception as e:
                    print(f"[Controller] Could not clear log {log_file}: {e}")

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def _setup_workspace(self):
        courses_dir = os.path.join(self.hub_dir, "Courses to Translate")
        if not os.path.exists(courses_dir):
            os.makedirs(courses_dir)

        if self.imscc_path:
            # If the path is relative and doesn't exist, check inside Courses to Translate/
            if not os.path.isabs(self.imscc_path) and not os.path.exists(self.imscc_path):
                alt_path = os.path.join(courses_dir, self.imscc_path)
                if os.path.exists(alt_path):
                    self.imscc_path = alt_path

            if not os.path.exists(self.imscc_path):
                print(f"[Controller] WARNING: IMSCC file {self.imscc_path} not found.")
                return
            
            base_name = os.path.basename(self.imscc_path)
            root_dir = os.path.splitext(base_name)[0]
            self.original_dir = os.path.join(courses_dir, root_dir)
            
            if not os.path.exists(self.original_dir):
                print(f"[Controller] Extracting {self.imscc_path} to {self.original_dir}")
                with zipfile.ZipFile(self.imscc_path, 'r') as zip_ref:
                    zip_ref.extractall(self.original_dir)
        else:
            if self.input_dir:
                root_dir = self.input_dir
            else:
                root_dir = self.instructions.get("project_overview", {}).get("root_directory", "career-development-english-master-export")
                
            self.original_dir = os.path.join(courses_dir, root_dir)
            
        # Example output dir: career-development-english-master-export_PTBR
        self.output_dir = f"{self.original_dir}_{self.target_language}"
        
        if not os.path.exists(self.output_dir):
            if os.path.exists(self.original_dir):
                print(f"[Controller] Creating workspace: {self.output_dir}")
                shutil.copytree(self.original_dir, self.output_dir)
            else:
                print(f"[Controller] WARNING: Original directory {self.original_dir} not found.")

        self._extract_course_info()

    def _extract_course_info(self):
        course_name = "Unknown Course"
        course_code = "UNKNOWN"
        manifest_path = os.path.join(self.original_dir, 'imsmanifest.xml')
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'xml')
                    title_tag = soup.find('lom:title') or soup.find('title')
                    if title_tag:
                        string_tag = title_tag.find('lom:string') or title_tag.find('string')
                        if string_tag:
                            course_name = string_tag.text.strip()
                        else:
                            course_name = title_tag.text.strip()
            except Exception as e:
                pass

        settings_path = os.path.join(self.original_dir, 'course_settings', 'course_settings.xml')
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'xml')
                    code_tag = soup.find('course_code')
                    if code_tag:
                        course_code = code_tag.text.strip()
                    title_tag = soup.find('title')
                    if title_tag and course_name == "Unknown Course":
                        course_name = title_tag.text.strip()
            except Exception as e:
                pass

        self._log(f"[System] CourseInfo: {course_name}|{course_code}")

    def _extract_and_log_links(self, filepath: str, content: str):
        # By user request, we no longer log every external link here. 
        # We now only export links to the Excel report if they were explicitly skipped.
        pass

    def _rewrite_church_links(self, content: str) -> str:
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

    def _clean_google_links(self, content: str, filepath: str) -> str:
        import urllib.parse
        import html
        import os
        
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
                self._log(f"[LinkBot] GoogleLinkStripped: {filename},{url},{final_url}")
                return final_url
            return url
            
        return re.sub(r'https?://(?:www\.)?google\.com/url\?[^\s"\'<>]*', replacer, content)

    def _load_instructions(self) -> dict:
        filepath = os.path.join(self.app_dir, "Course_Translation_Hub_ArchitectureAndInstructions.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        print("[Controller] WARNING: Instructions JSON not found.")
        return {}

    def _apply_custom_prompts(self):
        try:
            prompts = self.instructions.get("bot_instructions", {}).get("agent_prompts", {})
            
            # HTML Prompt
            html_prompt_key = f"HTMLTranslationAgent_{self.target_language}"
            if html_prompt_key in prompts:
                self.bots["html"].set_system_prompt(prompts[html_prompt_key])
                
        except Exception as e:
            print(f"[Controller] Error applying custom prompts: {e}")

    def process_directory(self):
        msg = f"Starting batch processing for directory: {self.output_dir}"
        print(f"\n[Controller] {msg}")
        self._log(msg)
        
        file_counts = collections.defaultdict(int)
        self.filepaths = []
        for root, dirs, files in os.walk(self.output_dir):
            for file in files:
                self.filepaths.append(os.path.join(root, file))
                ext = file.split('.')[-1].lower() if '.' in file else 'unknown'
                file_counts[ext] += 1
                
        # Log the file counts
        for ext, count in file_counts.items():
            self._log(f"[System] FileTypeCount: {ext}|{count}")
                
        # Phase 1: Pre-process Links (Sequential)
        self.pre_process_links()
        
        # Phase 2: Run translations (Concurrent)
        self.translate_files()
            
        self.compress_to_imscc()
        
    def pre_process_links(self):
        msg = "Starting Phase 1: Pre-processing and Mapping Links"
        print(f"\n[Controller] {msg}")
        self._log(msg)
        
        mapping_file = os.path.join(self.app_dir, "link_mapping.json")
        mapping = {}
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
                
        def save_mapping():
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, indent=2)

        import urllib.parse
        import html
        import re
        
        session_skipped_urls = set()

        def check_and_prompt(url, filepath, page_title=None):
            is_escaped = '&amp;' in url or '&#39;' in url or '&quot;' in url
            unescaped_url = html.unescape(url)
            clean_url = unescaped_url
            
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
                    filename = os.path.basename(filepath)
                    self._log(f"[LinkBot] GoogleLinkStripped: {filename},{url},{clean_url}")
                    
            if clean_url.startswith('https://www.churchofjesuschrist.org/study/scriptures'):
                if 'lang=eng' in clean_url:
                    lang_code = 'por' if self.target_language == 'PTBR' else 'spa'
                    localized_url = clean_url.replace('lang=eng', f'lang={lang_code}')
                    return html.escape(localized_url) if is_escaped else localized_url
                else:
                    # Link is likely already localized (e.g., lang=por) or has no lang parameter
                    return url

            if clean_url in mapping and mapping[clean_url].get(self.target_language):
                pt_link = mapping[clean_url][self.target_language]
                return html.escape(pt_link) if is_escaped else pt_link
                
            # Check if this URL is already a translated value (skip prompting if so)
            for translations in mapping.values():
                if clean_url in translations.values():
                    return url
                
            if not clean_url.startswith('http'):
                return url
                
            if clean_url in session_skipped_urls:
                return url
                
            if self.link_prompt_callback:
                display_name = page_title if page_title else os.path.basename(filepath)
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
                    
                    # Normalize Google Docs/Drive links for the user-provided PT link as well
                    if 'google.com' in pt_link:
                        pt_link = re.sub(r'/u/\d+/', '/', pt_link)
                        
                    if clean_url not in mapping:
                        mapping[clean_url] = {"PTBR": "", "SPA": ""}
                    mapping[clean_url][self.target_language] = pt_link
                    save_mapping()
                    
                    if comment:
                        self._log(f"[LinkBot] CommentedLink: {os.path.basename(filepath)},{clean_url},{comment}")
                    
                    return html.escape(pt_link) if is_escaped else pt_link
                else:
                    session_skipped_urls.add(clean_url)
                    if comment:
                        self._log(f"[LinkBot] SkippedLinkWithComment: {os.path.basename(filepath)},{clean_url},{comment}")
                    else:
                        self._log(f"[LinkBot] SkippedLink: {os.path.basename(filepath)},{clean_url}")
            
            return url

        for filepath in tqdm(self.filepaths, desc="Mapping Links", unit="file"):
            ext = filepath.split('.')[-1].lower() if '.' in filepath else ''
            
            if ext in ['html', 'htm', 'xml', 'qti']:
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    self._extract_and_log_links(filepath, content)
                    
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
                    
                    # Universal fallback for any remaining URLs
                    def universal_replacer(match):
                        return check_and_prompt(match.group(0), filepath, page_title)
                    new_content = re.sub(r'https?://[^\s"\'<>]+', universal_replacer, new_content)
                    
                    if new_content != content:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                except Exception as e:
                    print(f"[Controller] Error processing links in {filepath}: {e}")
                    
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
                    print(f"[Controller] Error processing txt links in {filepath}: {e}")

    def translate_files(self):
        msg = "Starting Phase 2: LLM Translation (Concurrent)"
        print(f"\n[Controller] {msg}")
        self._log(msg)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.process_file, path) for path in self.filepaths]
            for _ in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Translating", unit="file"):
                pass

    def compress_to_imscc(self):
        msg = "Compressing translated directory to IMSCC format..."
        print(f"\n[Controller] {msg}")
        self._log(msg)
        
        # Create a zip archive of the output directory where contents are at the root
        zip_path = shutil.make_archive(self.output_dir, 'zip', self.output_dir)
        
        # Rename .zip to .imscc
        imscc_path = self.output_dir + ".imscc"
        if os.path.exists(imscc_path):
            os.remove(imscc_path)
            
        os.rename(zip_path, imscc_path)
        
        msg = f"Successfully created course package: {imscc_path}"
        print(f"[Controller] {msg}")
        self._log(msg)

    def _is_already_translated(self, filepath: str, ext: str) -> bool:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            if ext in ["html", "xml", "qti"]:
                soup = BeautifulSoup(content, 'html.parser')
                text = soup.get_text(separator=' ').lower()
            else:
                text = content.lower()
                
            words = re.findall(r'\b[a-z]+\b', text)
            if len(words) < 10:
                return False
                
            en_stopwords = {"the", "and", "to", "of", "a", "in", "is", "that", "it", "with", "as", "for", "on", "this", "be"}
            pt_stopwords = {"de", "que", "o", "e", "do", "da", "em", "um", "para", "com", "nao", "os", "uma", "as", "se"}
            es_stopwords = {"de", "que", "el", "en", "y", "a", "los", "se", "del", "las", "un", "por", "con", "no", "una"}
            
            en_count = sum(1 for w in words if w in en_stopwords)
            
            target_count = 0
            if self.target_language == "PTBR":
                target_count = sum(1 for w in words if w in pt_stopwords)
            elif self.target_language == "ES":
                target_count = sum(1 for w in words if w in es_stopwords)
                
            if target_count > (en_count + 2):
                return True
                
            return False
        except Exception:
            return False

    def _extract_page_title(self, content: str, ext: str) -> str:
        try:
            if ext in ["html", "xml", "qti"]:
                soup = BeautifulSoup(content, 'xml' if ext in ['xml', 'qti'] else 'html.parser')
                title_tag = soup.find('title')
                if title_tag and title_tag.text:
                    return title_tag.text.strip()
        except Exception:
            pass
        return ""

    def process_file(self, filepath: str):
        filepath_abs = os.path.abspath(filepath)
        
        if filepath_abs.startswith(self.output_dir + os.sep):
            target_filepath = filepath_abs
        elif filepath_abs.startswith(self.original_dir + os.sep) or filepath_abs == self.original_dir:
            rel_path = os.path.relpath(filepath_abs, self.original_dir)
            target_filepath = os.path.join(self.output_dir, rel_path)
        else:
            target_filepath = filepath_abs

        if not os.path.exists(target_filepath):
            msg = f"File not found: {target_filepath}"
            self._log(msg)
            return

        ext = target_filepath.split('.')[-1].lower()
        
        if ext in ["ds_store"]:
            msg = f"Skipping ignored system file: {filepath}"
            self._log(msg)
            return
            
        if "setup-notes-and-course-settings" in target_filepath:
            msg = f"Skipping setup notes page: {filepath}"
            self._log(msg)
            return

        bot = self.bots.get(ext)
        if not bot:
            msg = f"Skipping unsupported file architecture for extension '{ext}': {filepath}"
            self._log(msg)
            return

        # Check if already translated
        if self._is_already_translated(target_filepath, ext):
            msg = f"Skipping already translated file: {filepath}"
            self._log(msg)
            return

        # 1. Translate
        msg = f"Delegating {target_filepath} to {bot.__class__.__name__}"
        self._log(msg)
        
        with open(target_filepath, "r", encoding="utf-8") as f:
            original_content = f.read()

        original_content = self._clean_google_links(original_content, target_filepath)
            
        if ext in ["html", "xml", "qti"]:
            self._extract_and_log_links(target_filepath, original_content)
            
        relevant_glossary = self.auditor.get_relevant_terms(original_content)
        relevant_scriptures = self.scripture_checker.get_scriptures_for_text(original_content)
            
        if "teaching-notes-and-student-outreach" in target_filepath.lower():
            custom_glossary = {
                "Dashboard": "Painel de controle",
                "Courses": "Cursos",
                "Calendar": "Calendário",
                "Inbox": "Caixa de entrada",
                "History": "Histórico",
                "Help": "Ajuda",
                "Syllabus": "Programa",
                "Modules": "Módulos",
                "Announcements": "Avisos",
                "Grades": "Notas",
                "People": "Pessoas",
                "Assignments": "Tarefas",
                "Discussions": "Fóruns",
                "Files": "Arquivos",
                "Outcomes": "Objetivos",
                "Pages": "Páginas",
                "Quizzes": "Testes",
                "Rubrics": "Rubricas",
                "Settings": "Configurações",
                "Teaching Notes and Student Outreach": "Plano de Aula e de Contato com Estudantes",
                "Instructor Information": "Informações do(a) Instrutor(a)",
                "Release Notes": "Relatório de Atualizações",
                "Purpose": "Objetivo",
                "Overview": "Visão Geral",
                "Centrally Managed Graders": "Avaliadores Gerenciados Centralmente",
                "Grade Adjustments": "Ajustes de Notas",
                "Student Portal": "Portal do Estudante",
                "Help Center": "Central de Ajuda",
                "Disruptive Students": "Estudantes Indisciplinados",
                "Dates and Late Work": "Datas e Atrasos no Trabalho",
                "Extra Credit": "Crédito Extra",
                "Every Week": "Toda Semana",
                "Weekly Learning Objectives": "Objetivos de Aprendizagem da Semana",
                "High-Stakes Assignment": "Tarefa Crucial",
                "Student Outreach": "Acompanhamento de Estudantes",
                "Non-participating and Failing Students": "Estudantes não participantes e ausentes",
                "Missing Assignments": "Tarefas Incompletas",
                "Low Performing Students": "Estudantes com baixo desempenho",
                "Positive Outreach": "Acompanhamento com feedback positivo",
                "Inspired Outreach": "Acompanhamento específico inspirado"
            }
            if relevant_glossary:
                relevant_glossary.update(custom_glossary)
            else:
                relevant_glossary = custom_glossary

        if ext in ["xml", "qti"]:
            translated_content = bot.translate_xml_content(original_content, relevant_glossary, relevant_scriptures)
        elif ext == "txt":
            translated_content = bot.translate_txt_content(original_content, relevant_glossary, relevant_scriptures)
        else:
            translated_content = bot.translate_html_content(original_content, relevant_glossary, relevant_scriptures)
        
        translated_content = self._rewrite_church_links(translated_content)
        
        # 3. Save
        self._log(f"Saving translated content to {target_filepath}")
        with open(target_filepath, "w", encoding="utf-8") as f:
            f.write(translated_content)
            
        self._log("Translation complete for this file.")
        
        page_title = self._extract_page_title(original_content, ext)
        if not page_title:
            page_title = os.path.splitext(os.path.basename(filepath))[0]
        self._log(f"[System] TranslatedPage: {page_title} | {filepath}")

    def update_excel_dashboard(self):
        msg = "Generating Excel Analytics Dashboard..."
        print(f"\n[Controller] {msg}")
        self._log(msg)
        
        data = []
        if os.path.exists(self.log_filepath):
            session_target = self.target_language
            with open(self.log_filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    session_match = re.match(r'--- New Session \(Target: (.*?)\) ---', line)
                    if session_match:
                        session_target = session_match.group(1)
                        continue
                        
                    log_match = re.match(r'\[(.*?)\] (.*)', line)
                    if log_match:
                        ts_str, message = log_match.group(1), log_match.group(2)
                        try:
                            timestamp = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                        except:
                            timestamp = None
                        
                        bot_name = 'System'
                        bot_match = re.match(r'^\[(.*?)\]\s*(.*)', message)
                        if bot_match:
                            bot_name = bot_match.group(1)
                            message = bot_match.group(2)

                        entry = {
                            'Timestamp': timestamp,
                            'Date': timestamp.date() if timestamp else None,
                            'Hour': timestamp.hour if timestamp else None,
                            'Target Language': session_target,
                            'Event Type': 'Log',
                            'Bot': bot_name,
                            'File Path': '',
                            'File Name': '',
                            'Status': 'Info',
                            'Message': message
                        }
                        
                        if message.startswith('Delegating '):
                            m = re.match(r'Delegating (.*) to (.*)', message)
                            if m:
                                entry['Event Type'] = 'Delegation'
                                entry['Status'] = 'Success'
                                entry['File Path'] = m.group(1)
                                entry['Bot'] = m.group(2)
                                entry['File Name'] = entry['File Path'].split('/')[-1]
                        elif message.startswith('Skipping ignored'):
                            entry['Event Type'] = 'Skipped'
                            entry['Status'] = 'Warning'
                            entry['File Path'] = message.replace('Skipping ignored system file: ', '')
                            entry['File Name'] = entry['File Path'].split('/')[-1]
                        elif message.startswith('Skipping already translated'):
                            entry['Event Type'] = 'Skipped (Already Translated)'
                            entry['Status'] = 'Info'
                            entry['File Path'] = message.replace('Skipping already translated file: ', '')
                            entry['File Name'] = entry['File Path'].split('/')[-1]
                        elif 'Skipping AuditorBot' in message:
                            entry['Event Type'] = 'Skipped (Size Limit)'
                            entry['Status'] = 'Warning'
                        elif message.startswith('CourseInfo: '):
                            entry['Event Type'] = 'Course Info'
                            entry['Message'] = message.replace('CourseInfo: ', '')
                            entry['Status'] = 'Info'
                        elif message.startswith('ExtLink: '):
                            entry['Event Type'] = 'External Link'
                            entry['Bot'] = 'LinkBot'
                            parts = message.replace('ExtLink: ', '').split(',', 2)
                            if len(parts) == 3:
                                entry['File Name'] = parts[0]
                                entry['Message'] = f"{parts[1]} | {parts[2]}"
                            entry['Status'] = 'Info'
                        elif message.startswith('GoogleLinkStripped: '):
                            entry['Event Type'] = 'Google Link Stripped'
                            entry['Bot'] = 'LinkBot'
                            parts = message.replace('GoogleLinkStripped: ', '').split(',', 2)
                            if len(parts) == 3:
                                entry['File Name'] = parts[0]
                                entry['Message'] = f"{parts[1]} | {parts[2]}"
                            entry['Status'] = 'Success'
                        elif message.startswith('CommentedLink: ') or message.startswith('SkippedLinkWithComment: '):
                            entry['Event Type'] = 'Commented Link'
                            entry['Bot'] = 'LinkBot'
                            if message.startswith('CommentedLink: '):
                                raw_data = message.replace('CommentedLink: ', '')
                                entry['Status'] = 'Success'
                            else:
                                raw_data = message.replace('SkippedLinkWithComment: ', '')
                                entry['Status'] = 'Warning'
                            parts = raw_data.split(',', 2)
                            if len(parts) == 3:
                                entry['File Name'] = parts[0]
                                entry['Message'] = f"{parts[1]} | {parts[2]}"
                        elif message.startswith('SkippedLink: '):
                            entry['Event Type'] = 'Skipped Link'
                            entry['Bot'] = 'LinkBot'
                            parts = message.replace('SkippedLink: ', '').split(',', 1)
                            if len(parts) == 2:
                                entry['File Name'] = parts[0]
                                entry['Message'] = parts[1]
                            entry['Status'] = 'Warning'
                        elif message.startswith('FileTypeCount: '):
                            entry['Event Type'] = 'File Type Count'
                            parts = message.replace('FileTypeCount: ', '').split('|', 1)
                            if len(parts) == 2:
                                entry['File Name'] = parts[0]
                                entry['Message'] = parts[1]
                            entry['Status'] = 'Info'
                        elif message.startswith('TranslatedPage: '):
                            entry['Event Type'] = 'Translated Page'
                            entry['Status'] = 'Success'
                            parts = message.replace('TranslatedPage: ', '').split(' | ', 1)
                            if len(parts) == 2:
                                entry['Message'] = parts[0]
                                entry['File Path'] = parts[1]
                                entry['File Name'] = parts[1].split('/')[-1]
                            else:
                                entry['Message'] = message.replace('TranslatedPage: ', '')
                        elif 'error' in message.lower() or 'exception' in message.lower():
                            entry['Status'] = 'Error'
                            entry['Event Type'] = 'Error'
                        elif 'Found references' in message or 'Found ' in message:
                            entry['Status'] = 'Success'
                            entry['Event Type'] = 'Extraction Found'
                            
                        data.append(entry)

        if not data:
            return
            
        df = pd.DataFrame(data)
        
        course_name = "Course"
        course_code = "UNKNOWN"
        course_info_rows = df[df['Event Type'] == 'Course Info']
        if not course_info_rows.empty:
            msg = course_info_rows.iloc[-1]['Message']
            parts = msg.split('|')
            if len(parts) >= 2:
                course_name = parts[0].strip()
                course_code = parts[1].strip()
                
        # Clean course_name for safe filename
        safe_course_name = "".join([c for c in course_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        if not safe_course_name:
            safe_course_name = "Course"
            
        excel_filename = f"{safe_course_name} Translation Report.xlsx"
        reports_dir = os.path.join(self.hub_dir, "Reports")
        os.makedirs(reports_dir, exist_ok=True)
        excel_path = os.path.join(reports_dir, excel_filename)
        workbook = xlsxwriter.Workbook(excel_path)

        # Custom Formats
        title_fmt = workbook.add_format({'bold': True, 'font_size': 26, 'font_color': '#2C3E50', 'bg_color': '#ECF0F1', 'align': 'center', 'valign': 'vcenter'})
        subtitle_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#7F8C8D', 'bg_color': '#ECF0F1', 'align': 'center'})
        header_fmt = workbook.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#34495E', 'border': 1, 'align': 'center'})
        cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'border': 1, 'valign': 'vcenter'})
        kpi_header_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'font_color': 'white', 'bg_color': '#2980B9', 'align': 'center', 'border': 1})
        kpi_val_fmt = workbook.add_format({'bold': True, 'font_size': 20, 'font_color': '#2C3E50', 'align': 'center', 'border': 1, 'bg_color': '#D6EAF8'})
        success_fmt = workbook.add_format({'bg_color': '#C8E6C9', 'font_color': '#1B5E20'})
        warning_fmt = workbook.add_format({'bg_color': '#FFE082', 'font_color': '#E65100'})
        error_fmt = workbook.add_format({'bg_color': '#FFCDD2', 'font_color': '#B71C1C'})

        # SHEET 1: Dashboard
        dash = workbook.add_worksheet('Dashboard')
        dash.hide_gridlines(2)
        dash.set_column('A:A', 2)
        dash.set_column('B:G', 20)
        dash.set_row(1, 40)
        dash.merge_range('B2:G2', 'Course Translation Hub Analytics', title_fmt)
        dash.merge_range('B3:G3', 'Automated Bot Performance & Log Analysis', subtitle_fmt)
        
        dash.merge_range('B4:G4', f'Course: {course_name} ({course_code})', workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'}))
        
        dash.write('B5', 'Total Log Events', kpi_header_fmt)
        dash.write_formula('B6', '=COUNTA(\'Raw Logs\'!A:A)-1', kpi_val_fmt)
        dash.write('D5', 'Successful Operations', kpi_header_fmt)
        dash.write_formula('D6', '=COUNTIF(\'Raw Logs\'!I:I, "Success")', kpi_val_fmt)
        dash.write('F5', 'Errors / Warnings', kpi_header_fmt)
        dash.write_formula('F6', '=COUNTIF(\'Raw Logs\'!I:I, "Error") + COUNTIF(\'Raw Logs\'!I:I, "Warning")', kpi_val_fmt)
        
        dash.write('B8', 'Filter Bot Activity:', workbook.add_format({'bold': True, 'font_size': 12}))
        bots_list = list(df['Bot'].dropna().unique())
        if bots_list:
            dash.data_validation('C8', {'validate': 'list', 'source': bots_list})
            dash.write('C8', bots_list[0], workbook.add_format({'border': 1, 'bg_color': '#FFFFE0'}))
        dash.write('B9', 'Events for Selected Bot:', workbook.add_format({'bold': True}))
        dash.write_formula('C9', '=COUNTIF(\'Raw Logs\'!F:F, C8)', workbook.add_format({'bold': True, 'font_size': 14, 'color': '#2980B9'}))
        
        dash.write('B11', 'Hourly Activity Timeline', workbook.add_format({'bold': True, 'font_size': 14}))
        dash.write_row('B12', ['Hour', 'Event Count', 'Trend'], header_fmt)
        for i in range(24):
            row = 12 + i
            dash.write(row, 1, i, cell_fmt)
            dash.write_formula(row, 2, f'=COUNTIFS(\'Raw Logs\'!C:C, {i})', cell_fmt)
            
        dash.add_sparkline('D13', {'range': 'Dashboard!C13:C36', 'type': 'column', 'style': 4})
        dash.merge_range('D13:D36', '', cell_fmt)
        
        chart = workbook.add_chart({'type': 'area'})
        chart.add_series({
            'name': 'Hourly Events',
            'categories': ['Dashboard', 12, 1, 35, 1],
            'values': ['Dashboard', 12, 2, 35, 2],
            'fill': {'color': '#5DADE2', 'transparency': 30},
            'border': {'color': '#2874A6'}
        })
        chart.set_title({'name': 'Log Events Timeline (24h)'})
        chart.set_x_axis({'name': 'Hour of Day'})
        chart.set_y_axis({'name': 'Event Count'})
        chart.set_legend({'none': True})
        dash.insert_chart('E11', chart, {'x_scale': 1.1, 'y_scale': 1.4})

        # Add Skipped Files
        dash.write('I5', 'Skipped Files', header_fmt)
        dash.set_column('I:I', 40)
        skipped_df = df[df['Event Type'].str.contains('Skipped', na=False)]
        row_idx = 5
        for idx, row in skipped_df.iterrows():
            dash.write(row_idx, 8, str(row['File Name']), cell_fmt)
            row_idx += 1
            
        # Add File Type Counts
        dash.write('K5', 'File Extension', header_fmt)
        dash.write('L5', 'Total Count', header_fmt)
        dash.set_column('K:L', 15)
        
        file_counts_rows = df[df['Event Type'] == 'File Type Count']
        row_idx = 5
        for idx, row in file_counts_rows.iterrows():
            dash.write(row_idx, 10, str(row['File Name']), cell_fmt)
            dash.write(row_idx, 11, int(row['Message']), cell_fmt)
            row_idx += 1
            
        # Add External Links Log
        start_row = 40
        dash.write(start_row, 1, 'External Links Log', workbook.add_format({'bold': True, 'font_size': 14}))
        dash.write_row(start_row+1, 1, ['Location (Page Name)', 'Link Text', 'Link'], header_fmt)
        dash.set_column('B:B', 30)
        dash.set_column('C:C', 40)
        dash.set_column('D:D', 60)
        
        links_df = df[df['Event Type'] == 'External Link']
        r_idx = start_row + 2
        for idx, row in links_df.iterrows():
            loc = str(row['File Name'])
            msg = str(row['Message'])
            parts = msg.split(' | ', 1)
            link_text = parts[0] if len(parts) > 0 else ""
            link_url = parts[1] if len(parts) > 1 else ""
            
            dash.write(r_idx, 1, loc, cell_fmt)
            dash.write(r_idx, 2, link_text, cell_fmt)
            dash.write(r_idx, 3, link_url, cell_fmt)
            r_idx += 1

        # SHEET 2: Bot Statistics
        bot_stats = workbook.add_worksheet('Bot Analysis')
        bot_stats.set_column('A:E', 20)
        bot_stats.write_row('A1', ['Bot Name', 'Total Events', 'Successes', 'Warnings', 'Errors'], header_fmt)
        
        row_idx = 1
        for bot in bots_list:
            bot_stats.write(row_idx, 0, bot, cell_fmt)
            bot_stats.write_formula(row_idx, 1, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}")', cell_fmt)
            bot_stats.write_formula(row_idx, 2, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}", \'Raw Logs\'!I:I, "Success")', cell_fmt)
            bot_stats.write_formula(row_idx, 3, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}", \'Raw Logs\'!I:I, "Warning")', cell_fmt)
            bot_stats.write_formula(row_idx, 4, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}", \'Raw Logs\'!I:I, "Error")', cell_fmt)
            row_idx += 1
            
        bot_chart = workbook.add_chart({'type': 'column', 'subtype': 'stacked'})
        bot_chart.add_series({
            'name': 'Successes',
            'categories': ['Bot Analysis', 1, 0, row_idx-1, 0],
            'values': ['Bot Analysis', 1, 2, row_idx-1, 2],
            'fill': {'color': '#4CAF50'}
        })
        bot_chart.add_series({
            'name': 'Warnings',
            'categories': ['Bot Analysis', 1, 0, row_idx-1, 0],
            'values': ['Bot Analysis', 1, 3, row_idx-1, 3],
            'fill': {'color': '#FFC107'}
        })
        bot_chart.add_series({
            'name': 'Errors',
            'categories': ['Bot Analysis', 1, 0, row_idx-1, 0],
            'values': ['Bot Analysis', 1, 4, row_idx-1, 4],
            'fill': {'color': '#F44336'}
        })
        bot_chart.set_title({'name': 'Bot Reliability Breakdown'})
        bot_stats.insert_chart('A10', bot_chart, {'x_scale': 1.5, 'y_scale': 1.5})

        # SHEET 3: Raw Logs
        logs_sheet = workbook.add_worksheet('Raw Logs')
        logs_sheet.set_tab_color('#95A5A6')
        
        columns = list(df.columns)
        logs_sheet.write_row('A1', columns, header_fmt)
        
        for r_num, row_data in df.iterrows():
            for c_num, val in enumerate(row_data):
                if pd.isna(val):
                    val = ''
                if columns[c_num] == 'Timestamp' and val != '':
                    logs_sheet.write_datetime(r_num+1, c_num, val, date_fmt)
                else:
                    logs_sheet.write(r_num+1, c_num, val, cell_fmt)
                    
        logs_sheet.set_column('A:A', 20)
        logs_sheet.set_column('B:D', 12)
        logs_sheet.set_column('E:F', 20)
        logs_sheet.set_column('G:H', 30)
        logs_sheet.set_column('I:I', 15)
        logs_sheet.set_column('J:J', 80)
        logs_sheet.autofilter(0, 0, len(df), len(columns)-1)
        
        logs_sheet.conditional_format(1, 8, len(df), 8, {'type': 'cell', 'criteria': '==', 'value': '"Success"', 'format': success_fmt})
        logs_sheet.conditional_format(1, 8, len(df), 8, {'type': 'cell', 'criteria': '==', 'value': '"Warning"', 'format': warning_fmt})
        logs_sheet.conditional_format(1, 8, len(df), 8, {'type': 'cell', 'criteria': '==', 'value': '"Error"', 'format': error_fmt})

        # SHEET 4: Translated Pages
        translated_pages_df = df[df['Event Type'] == 'Translated Page'].copy()
        
        if not translated_pages_df.empty:
            # Deduplicate based on 'Message' (which is the page_title) and 'File Path'
            translated_pages_df = translated_pages_df.drop_duplicates(subset=['Message', 'File Path'])
            
            # Now find duplicate page titles (same title, different file paths)
            title_counts = translated_pages_df['Message'].value_counts()
            translated_pages_df['Duplicate Flag'] = translated_pages_df['Message'].apply(
                lambda x: 'Duplicate Name' if title_counts.get(x, 0) > 1 else ''
            )
            
            # Create sheet
            pages_sheet = workbook.add_worksheet('Translated Pages')
            pages_sheet.set_column('A:A', 60)
            pages_sheet.set_column('B:B', 20)
            
            pages_sheet.write('A1', 'Page Name', header_fmt)
            pages_sheet.write('B1', 'Flag', header_fmt)
            
            r_idx = 1
            for idx, row in translated_pages_df.iterrows():
                pages_sheet.write(r_idx, 0, str(row['Message']), cell_fmt)
                flag = str(row['Duplicate Flag'])
                if flag:
                    pages_sheet.write(r_idx, 1, flag, warning_fmt)
                else:
                    pages_sheet.write(r_idx, 1, '', cell_fmt)
                r_idx += 1

        # SHEET 5: Stripped Google Links
        stripped_links_df = df[df['Event Type'] == 'Google Link Stripped'].copy()
        
        if not stripped_links_df.empty:
            stripped_sheet = workbook.add_worksheet('Google Links')
            stripped_sheet.set_column('A:A', 30)
            stripped_sheet.set_column('B:B', 60)
            stripped_sheet.set_column('C:C', 60)
            
            stripped_sheet.write('A1', 'Page Name', header_fmt)
            stripped_sheet.write('B1', 'Original URL', header_fmt)
            stripped_sheet.write('C1', 'Clean URL', header_fmt)
            
            r_idx = 1
            for idx, row in stripped_links_df.iterrows():
                loc = str(row['File Name'])
                msg = str(row['Message'])
                parts = msg.split(' | ', 1)
                orig_url = parts[0] if len(parts) > 0 else ""
                clean_url = parts[1] if len(parts) > 1 else ""
                
                stripped_sheet.write(r_idx, 0, loc, cell_fmt)
                stripped_sheet.write(r_idx, 1, orig_url, cell_fmt)
                stripped_sheet.write(r_idx, 2, clean_url, cell_fmt)
                r_idx += 1

        # SHEET 6: Skipped Links
        skipped_links_df = df[df['Event Type'] == 'Skipped Link'].copy()
        
        if not skipped_links_df.empty:
            skipped_sheet = workbook.add_worksheet('Skipped Links')
            skipped_sheet.set_column('A:A', 30)
            skipped_sheet.set_column('B:B', 90)
            
            skipped_sheet.write('A1', 'Page Name', header_fmt)
            skipped_sheet.write('B1', 'Unmapped English URL', header_fmt)
            
            r_idx = 1
            for idx, row in skipped_links_df.iterrows():
                loc = str(row['File Name'])
                msg = str(row['Message'])
                
                skipped_sheet.write(r_idx, 0, loc, cell_fmt)
                skipped_sheet.write(r_idx, 1, msg, cell_fmt)
                r_idx += 1

        # SHEET 7: Commented Links
        commented_links_df = df[df['Event Type'] == 'Commented Link'].copy()
        
        if not commented_links_df.empty:
            comments_sheet = workbook.add_worksheet('Commented Links')
            comments_sheet.set_column('A:A', 30)
            comments_sheet.set_column('B:B', 60)
            comments_sheet.set_column('C:C', 60)
            
            comments_sheet.write('A1', 'Page Name', header_fmt)
            comments_sheet.write('B1', 'URL', header_fmt)
            comments_sheet.write('C1', 'Comment', header_fmt)
            
            r_idx = 1
            for idx, row in commented_links_df.iterrows():
                loc = str(row['File Name'])
                msg = str(row['Message'])
                parts = msg.split(' | ', 1)
                link_url = parts[0] if len(parts) > 0 else ""
                comment = parts[1] if len(parts) > 1 else ""
                
                comments_sheet.write(r_idx, 0, loc, cell_fmt)
                comments_sheet.write(r_idx, 1, link_url, cell_fmt)
                comments_sheet.write(r_idx, 2, comment, cell_fmt)
                r_idx += 1

        workbook.close()
        print(f"[Controller] Excel successfully created: {excel_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Course Translation Hub Controller Bot")
    parser.add_argument("--file", help="Specific file to translate")
    parser.add_argument("--dir", help="Directory folder to process")
    parser.add_argument("--imscc", help="IMSCC course package to process")
    parser.add_argument("--lang", choices=["PTBR", "ES"], help="Target Language")
    
    args = parser.parse_args()
    
    target_language = args.lang
    if not target_language:
        lang_input = input("Which language would you like to translate to? (Enter 'PTBR' or 'ES'): ").strip().upper()
        if lang_input in ["PTBR", "ES"]:
            target_language = lang_input
        else:
            print("Invalid language selected. Defaulting to PTBR.")
            target_language = "PTBR"
            
    controller = TranslationController(target_language=target_language, input_dir=args.dir, imscc_path=args.imscc)
    
    if args.file:
        controller.process_file(args.file)
        controller.update_excel_dashboard()
    elif args.dir or args.imscc:
        controller.process_directory()
        controller.update_excel_dashboard()
    else:
        print("[Controller] Running in test mode. Please provide --file, --dir, or --imscc to process.")
        print("Example: python controller.py --imscc course.imscc")
