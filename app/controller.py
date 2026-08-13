import os
import argparse
import concurrent.futures
from tqdm import tqdm
import json
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

from bots.html_bot import HTMLTranslationBot
from bots.xml_bot import XMLTranslationBot
from bots.txt_bot import TextTranslationBot
from bots.auditor_bot import GlossaryAuditBot
from bots.scripturecheck_bot import ScriptureCheckBot

from core.workspace_manager import WorkspaceManager
from core.link_processor import LinkProcessor
from core.dashboard_generator import DashboardGenerator

class TranslationController:
    def __init__(self, target_language="PTBR", input_dir=None, imscc_path=None, link_prompt_callback=None):
        self.target_language = target_language
        self.link_prompt_callback = link_prompt_callback
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.hub_dir = os.path.dirname(self.app_dir)
        self._clear_logs()
        
        self.instructions = self._load_instructions()
        self.auditor = GlossaryAuditBot(target_language=self.target_language, hub_dir=self.hub_dir)
        self.scripture_checker = ScriptureCheckBot(target_language=self.target_language, hub_dir=self.hub_dir)
        
        self.bots = {
            "html": HTMLTranslationBot(target_language=self.target_language),
            "xml": XMLTranslationBot(target_language=self.target_language),
            "qti": XMLTranslationBot(target_language=self.target_language), 
            "txt": TextTranslationBot(target_language=self.target_language)
        }
        
        self._apply_custom_prompts()
        self.log_filepath = os.path.join(self.app_dir, "bots", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New Session (Target: {self.target_language}) ---\n")
            
        self.workspace = WorkspaceManager(self.target_language, self.hub_dir, input_dir, imscc_path)
        default_root = self.instructions.get("project_overview", {}).get("root_directory", "career-development-english-master-export")
        if self.workspace.setup_workspace(default_root):
            self.workspace.extract_course_info(self._log)
            
        self.link_processor = LinkProcessor(self.target_language, self.app_dir, [], self.link_prompt_callback)

    def _clear_logs(self):
        log_files = ["translation_log.txt", "html_bot_log.txt", "xml_bot_log.txt", "txt_bot_log.txt", "auditor_bot_log.txt", "scripture_bot_log.txt"]
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
            html_prompt_key = f"HTMLTranslationAgent_{self.target_language}"
            if html_prompt_key in prompts:
                self.bots["html"].set_system_prompt(prompts[html_prompt_key])
        except Exception as e:
            print(f"[Controller] Error applying custom prompts: {e}")

    def process_directory(self):
        msg = f"Starting batch processing for directory: {self.workspace.output_dir}"
        print(f"\n[Controller] {msg}")
        self._log(msg)
        
        self.filepaths = self.workspace.collect_files(self._log)
        self.link_processor.filepaths = self.filepaths
        self.link_processor.pre_process_links(self._log)
        self.translate_files()
        self.workspace.compress_to_imscc(self._log)
        
    def translate_files(self):
        msg = "Starting Phase 2: LLM Translation (Concurrent)"
        print(f"\n[Controller] {msg}")
        self._log(msg)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.process_file, path) for path in self.filepaths]
            for _ in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Translating", unit="file"):
                pass

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
            if len(words) < 10: return False
                
            en_stopwords = {"the", "and", "to", "of", "a", "in", "is", "that", "it", "with", "as", "for", "on", "this", "be"}
            pt_stopwords = {"de", "que", "o", "e", "do", "da", "em", "um", "para", "com", "nao", "os", "uma", "as", "se"}
            es_stopwords = {"de", "que", "el", "en", "y", "a", "los", "se", "del", "las", "un", "por", "con", "no", "una"}
            
            en_count = sum(1 for w in words if w in en_stopwords)
            target_count = sum(1 for w in words if w in (pt_stopwords if self.target_language == "PTBR" else es_stopwords))
                
            if target_count > (en_count + 2): return True
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
        target_filepath = self.workspace.get_target_filepath(filepath)

        if not os.path.exists(target_filepath):
            self._log(f"File not found: {target_filepath}")
            return

        ext = target_filepath.split('.')[-1].lower()
        if ext in ["ds_store"]:
            self._log(f"Skipping ignored system file: {filepath}")
            return
            
        if "setup-notes-and-course-settings" in target_filepath:
            self._log(f"Skipping setup notes page: {filepath}")
            return

        bot = self.bots.get(ext)
        if not bot:
            self._log(f"Skipping unsupported file architecture for extension '{ext}': {filepath}")
            return

        if self._is_already_translated(target_filepath, ext):
            self._log(f"Skipping already translated file: {filepath}")
            return

        self._log(f"Delegating {target_filepath} to {bot.__class__.__name__}")
        
        with open(target_filepath, "r", encoding="utf-8") as f:
            original_content = f.read()

        original_content = self.link_processor.clean_google_links(original_content, target_filepath, self._log)
            
        relevant_glossary = self.auditor.get_relevant_terms(original_content)
        relevant_scriptures = self.scripture_checker.get_scriptures_for_text(original_content)
            
        if "teaching-notes-and-student-outreach" in target_filepath.lower():
            custom_glossary = {
                "Dashboard": "Painel de controle", "Courses": "Cursos", "Calendar": "Calendário", 
                "Inbox": "Caixa de entrada", "History": "Histórico", "Help": "Ajuda", 
                "Syllabus": "Programa", "Modules": "Módulos", "Announcements": "Avisos", 
                "Grades": "Notas", "People": "Pessoas", "Assignments": "Tarefas", 
                "Discussions": "Fóruns", "Files": "Arquivos", "Outcomes": "Objetivos", 
                "Pages": "Páginas", "Quizzes": "Testes", "Rubrics": "Rubricas", 
                "Settings": "Configurações", "Teaching Notes and Student Outreach": "Plano de Aula e de Contato com Estudantes"
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
        
        translated_content = self.link_processor.rewrite_church_links(translated_content)
        
        self._log(f"Saving translated content to {target_filepath}")
        with open(target_filepath, "w", encoding="utf-8") as f:
            f.write(translated_content)
            
        self._log("Translation complete for this file.")
        
        page_title = self._extract_page_title(original_content, ext)
        if not page_title:
            page_title = os.path.splitext(os.path.basename(filepath))[0]
        self._log(f"[System] TranslatedPage: {page_title} | {filepath}")

    def update_excel_dashboard(self):
        generator = DashboardGenerator(self.log_filepath, self.hub_dir, self.target_language)
        generator.generate(self._log)


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
