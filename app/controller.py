import os
import argparse
import concurrent.futures
import hashlib
import shutil
from tqdm import tqdm
import json
import re
import threading
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
    ATTENTION_PAGE_FILENAME = "attention-messaging-instructors-and-graders.html"
    ATTENTION_PAGE_EN_TITLE = "Attention: Messaging Instructors and Graders"
    ATTENTION_PAGE_PTBR_TITLE = "Atenção: Mensagens para instrutores e avaliadores"
    ATTENTION_IMAGE_SPECS = (
        (
            "atencao mensagens para instrutores e avaliadores 1.png",
            "attention-messaging-instructors-graders-ptbr-1.png",
        ),
        (
            "atencao mensagens para instrutores e avaliadores 2.png",
            "attention-messaging-instructors-graders-ptbr-2.png",
        ),
    )

    def __init__(self, target_language="PTBR", input_dir=None, imscc_path=None, link_prompt_callback=None, target_course_id=None):
        self.target_language = target_language
        self.link_prompt_callback = link_prompt_callback
        self.target_course_id = target_course_id
        self._attention_package_prepared = False
        self._attention_page_present = False
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.hub_dir = os.path.dirname(self.app_dir)
        self._clear_logs()
        
        self.instructions = self._load_instructions()
        
        self.log_lock = threading.Lock()
        
        self.auditor = GlossaryAuditBot(target_language=self.target_language, hub_dir=self.hub_dir, log_lock=self.log_lock)
        self.scripture_checker = ScriptureCheckBot(target_language=self.target_language, hub_dir=self.hub_dir, log_lock=self.log_lock)
        
        self.log_filepath = os.path.join(self.app_dir, "bots", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New Session (Target: {self.target_language}) ---\n")
            
        self.workspace = WorkspaceManager(self.target_language, self.hub_dir, input_dir, imscc_path)
        default_root = self.instructions.get("project_overview", {}).get("root_directory", "career-development-english-master-export")
        workspace_dir = None
        if self.workspace.setup_workspace(default_root):
            self.workspace.extract_course_info(self._log)
            workspace_dir = self.workspace.output_dir
            
        self.bots = {
            "html": HTMLTranslationBot(target_language=self.target_language, log_lock=self.log_lock, workspace_dir=workspace_dir),
            "xml": XMLTranslationBot(target_language=self.target_language, log_lock=self.log_lock, workspace_dir=workspace_dir),
            "qti": XMLTranslationBot(target_language=self.target_language, log_lock=self.log_lock, workspace_dir=workspace_dir), 
            "txt": TextTranslationBot(target_language=self.target_language, log_lock=self.log_lock)
        }
        
        self._apply_custom_prompts()
            
        self.link_processor = LinkProcessor(self.target_language, self.app_dir, [], self.link_prompt_callback)

    def _clear_logs(self):
        log_files = ["translation_log.txt"]
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
        with self.log_lock:
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
            for ext, bot_key in [("html", "HTMLTranslationAgent"), ("xml", "XMLTranslationAgent"), ("qti", "QTITranslationAgent"), ("txt", "TextTranslationAgent")]:
                prompt_key = f"{bot_key}_{self.target_language}"
                if prompt_key in prompts:
                    self.bots[ext].set_system_prompt(prompts[prompt_key])
                else:
                    print(f"[Controller] WARNING: No custom prompt found for '{prompt_key}'. Bot '{ext}' will use its default prompt.")
        except Exception as e:
            print(f"[Controller] Error applying custom prompts: {e}")

    def process_directory(self):
        msg = f"Starting batch processing for directory: {self.workspace.output_dir}"
        print(f"\n[Controller] {msg}")
        self._log(msg)

        # This must happen before file collection and concurrent translation.
        # imsmanifest.xml is one of the translated files, so modifying it from
        # the attention-page worker would create a write race.
        self._prepare_attention_messaging_package()

        self.filepaths = self.workspace.collect_files(self._log)
        self.link_processor.filepaths = self.filepaths
        self.link_processor.pre_process_links(self._log)
        self.translate_files()
        self.workspace.compress_to_imscc(self._log)
        

        
    def translate_files(self):
        msg = "Starting Phase 2: LLM Translation (Concurrent)"
        print(f"\n[Controller] {msg}")
        self._log(msg)
        failures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.process_file, path): path
                for path in self.filepaths
            }
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Translating", unit="file"):
                filepath = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    failures.append((filepath, exc))
                    self._log(f"[System] Error: Translation failed for {filepath}: {exc}")

        if failures:
            self._log(
                f"[System] Retrying {len(failures)} failed translation file(s) sequentially."
            )
            print(
                f"\n[Controller] Retrying {len(failures)} failed translation "
                "file(s) one at a time..."
            )
            retry_failures = []
            for filepath, _first_error in failures:
                try:
                    self.process_file(filepath)
                    self._log(f"[System] Retry succeeded for {filepath}")
                except Exception as exc:
                    retry_failures.append((filepath, exc))
                    self._log(f"[System] Retry failed for {filepath}: {exc}")

            if retry_failures:
                failure_details = "; ".join(
                    f"{os.path.basename(filepath)}: {exc}"
                    for filepath, exc in retry_failures
                )
                is_imscc_run = bool(
                    getattr(getattr(self, "workspace", None), "imscc_path", None)
                )
                outcome = (
                    "The IMSCC package was not created"
                    if is_imscc_run
                    else "The translated output was not completed"
                )
                raise RuntimeError(
                    f"Translation failed for {len(retry_failures)} file(s) after retry. "
                    f"{outcome}. Failed file details: {failure_details}"
                )

    def _is_teaching_notes_page(self, filepath: str) -> bool:
        filename = os.path.basename(filepath).lower()
        return filename.endswith(".html") and "teaching-notes" in filename

    def _is_attention_messaging_page(self, filepath: str, content: str = "") -> bool:
        if self.target_language != "PTBR":
            return False

        filename = os.path.basename(filepath).lower()
        if filename == self.ATTENTION_PAGE_FILENAME:
            return True

        if not content:
            return False

        try:
            title = BeautifulSoup(content, "html.parser").find("title")
            title_text = title.get_text(strip=True) if title else ""
            return title_text.casefold() in {
                self.ATTENTION_PAGE_EN_TITLE.casefold(),
                self.ATTENTION_PAGE_PTBR_TITLE.casefold(),
            }
        except Exception:
            return False

    def _find_attention_messaging_pages(self) -> list:
        wiki_dir = os.path.join(self.workspace.output_dir, "wiki_content")
        if not os.path.isdir(wiki_dir):
            return []

        matches = []
        for filename in os.listdir(wiki_dir):
            if not filename.lower().endswith(".html"):
                continue
            filepath = os.path.join(wiki_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue
            if self._is_attention_messaging_page(filepath, content):
                matches.append(filepath)
        return matches

    def _register_attention_images_in_manifest(self, manifest_path: str):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = f.read()

        existing_hrefs = {
            match.group(2)
            for match in re.finditer(
                r"\bhref\s*=\s*(['\"])(.*?)\1",
                manifest,
                flags=re.IGNORECASE,
            )
        }
        missing_entries = []
        for _source_name, packaged_name in self.ATTENTION_IMAGE_SPECS:
            href = f"web_resources/Uploaded Media/{packaged_name}"
            if href in existing_hrefs:
                continue
            identifier = "g" + hashlib.sha1(href.encode("utf-8")).hexdigest()
            missing_entries.append(
                f'    <resource type="webcontent" identifier="{identifier}" href="{href}">\n'
                f'      <file href="{href}"/>\n'
                f'    </resource>'
            )

        if not missing_entries:
            return

        closing_tag = re.search(
            r"^[ \t]*</(?:[A-Za-z_][\w.-]*:)?resources\s*>",
            manifest,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if not closing_tag:
            raise RuntimeError(
                "Could not package the Portuguese attention-page images because "
                "imsmanifest.xml has no closing <resources> element."
            )

        insertion = "\n".join(missing_entries) + "\n"
        manifest = (
            manifest[:closing_tag.start()]
            + insertion
            + manifest[closing_tag.start():]
        )
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(manifest)

    def _prepare_attention_messaging_package(self) -> bool:
        if self.target_language != "PTBR":
            return False
        if getattr(self, "_attention_package_prepared", False):
            return getattr(self, "_attention_page_present", False)

        page_paths = self._find_attention_messaging_pages()
        if not page_paths:
            self._attention_package_prepared = True
            self._attention_page_present = False
            return False

        common_images_dir = os.path.join(self.hub_dir, "Common Course Images")
        missing_images = [
            source_name
            for source_name, _packaged_name in self.ATTENTION_IMAGE_SPECS
            if not os.path.isfile(os.path.join(common_images_dir, source_name))
        ]
        if missing_images:
            raise FileNotFoundError(
                "Cannot build the Portuguese attention page. Missing common course "
                f"image(s): {', '.join(missing_images)}"
            )

        manifest_path = os.path.join(self.workspace.output_dir, "imsmanifest.xml")
        if not os.path.isfile(manifest_path):
            raise FileNotFoundError(
                "Cannot package the Portuguese attention-page images because "
                f"imsmanifest.xml was not found at {manifest_path}"
            )

        media_dir = os.path.join(
            self.workspace.output_dir,
            "web_resources",
            "Uploaded Media",
        )
        os.makedirs(media_dir, exist_ok=True)
        for source_name, packaged_name in self.ATTENTION_IMAGE_SPECS:
            shutil.copy2(
                os.path.join(common_images_dir, source_name),
                os.path.join(media_dir, packaged_name),
            )

        self._register_attention_images_in_manifest(manifest_path)
        self._attention_package_prepared = True
        self._attention_page_present = True
        self._log(
            "[Controller] Packaged Portuguese images for "
            f"{self.ATTENTION_PAGE_FILENAME}"
        )
        return True

    def _build_attention_messaging_page(self, original_content: str) -> str:
        first_image = self.ATTENTION_IMAGE_SPECS[0][1]
        second_image = self.ATTENTION_IMAGE_SPECS[1][1]
        body_html = f'''<p>Estudantes que t&ecirc;m d&uacute;vidas sobre a pontua&ccedil;&atilde;o ou notas das tarefas devem contatar a equipe de avalia&ccedil;&atilde;o atrav&eacute;s da caixa "Adicionar um Coment&aacute;rio" ao trabalhar na &aacute;rea de envio de suas tarefas.&nbsp;</p>
<p><img src="$IMS-CC-FILEBASE$/Uploaded%20Media/{first_image}" alt="Captura de tela da p&aacute;gina de tarefas do Canvas mostrando a op&ccedil;&atilde;o de adicionar um coment&aacute;rio. No topo, o t&iacute;tulo 'Adicionar um Coment&aacute;rio:' seguido por uma grande caixa de texto vazia. Abaixo, os links 'Coment&aacute;rio de M&iacute;dia' (com um &iacute;cone de &aacute;udio ao lado) e 'Anexar Arquivo'. Na parte inferior, h&aacute; um bot&atilde;o azul com a palavra 'Salvar'" width="334" height="243" /></p>
<p><span data-teams="true">Os avaliadores <i><strong>n&atilde;o podem responder a perguntas</strong></i> enviadas aos "Assistentes de Ensino" por meio da Caixa de Entrada do curso ou da aba Comunica&ccedil;&otilde;es. Al&eacute;m disso, este curso <i><strong>n&atilde;o</strong></i> utiliza Assistentes de Ensino (AEs).</span></p>
<p><span>Os estudantes <em><strong>devem usar o recurso Inbox para se comunicar com o instrutor</strong></em> sobre quest&otilde;es pessoais ou outras d&uacute;vidas sobre o curso ou conte&uacute;do do curso. Eles podem se comunicar com o instrutor escolhendo a op&ccedil;&atilde;o "Instrutores" na lista suspensa "Para" ao compor uma mensagem no Inbox.&nbsp;</span></p>
<p><img src="$IMS-CC-FILEBASE$/Uploaded%20Media/{second_image}" alt="Captura de tela do cabe&ccedil;alho da janela de emails do Canvas com o t&iacute;tulo &quot;Compor mensagem&quot;. O campo &quot;Curso&quot; est&aacute; preenchido com o curso referido. O campo &quot;Para *&quot; exibe um menu suspenso com op&ccedil;&otilde;es de destinat&aacute;rios. Sobrepostas &agrave; imagem, h&aacute; anota&ccedil;&otilde;es em vermelho para orientar o usu&aacute;rio: uma seta com a palavra &quot;SIM&quot; aponta para a op&ccedil;&atilde;o &quot;Instrutores&quot; (que est&aacute; destacada em amarelo), indicando a escolha correta. Outra seta com a palavra &quot;N&Atilde;O&quot; aponta para a op&ccedil;&atilde;o &quot;Assistentes&quot;, indicando que ela n&atilde;o deve ser selecionada." width="429" height="239" /></p>
<p>&nbsp;</p>
<p>&nbsp;</p>'''

        title_html = "Aten&ccedil;&atilde;o: Mensagens para instrutores e avaliadores"
        title_pattern = re.compile(r"<title\b[^>]*>.*?</title\s*>", re.IGNORECASE | re.DOTALL)
        if title_pattern.search(original_content):
            updated = title_pattern.sub(f"<title>{title_html}</title>", original_content, count=1)
        else:
            head_close = re.search(r"</head\s*>", original_content, flags=re.IGNORECASE)
            if not head_close:
                raise RuntimeError(
                    "Cannot build the Portuguese attention page because its HTML "
                    "contains neither a <title> nor a closing <head> element."
                )
            updated = (
                original_content[:head_close.start()]
                + f"<title>{title_html}</title>\n"
                + original_content[head_close.start():]
            )

        body_pattern = re.compile(
            r"(<body\b[^>]*>).*?(</body\s*>)",
            re.IGNORECASE | re.DOTALL,
        )
        if not body_pattern.search(updated):
            raise RuntimeError(
                "Cannot build the Portuguese attention page because its HTML has "
                "no complete <body> element."
            )
        return body_pattern.sub(
            lambda match: f"{match.group(1)}\n{body_html}\n{match.group(2)}",
            updated,
            count=1,
        )

    def _enforce_teaching_notes_title(self, content: str) -> str:
        title_translations = {
            "PTBR": {
                "Teaching Notes and Student Outreach": "Plano de Aula e de Contato Com Os Estudantes",
                "Teaching Notes": "Notas de Ensino",
            },
            "SPA": {
                "Teaching Notes and Student Outreach": "Notas de enseñanza y contacto con los estudiantes",
                "Teaching Notes": "Notas de enseñanza",
            },
        }
        translations = title_translations.get(self.target_language)
        if not translations:
            return content

        content = content.replace(
            "Teaching Notes and Student Outreach",
            translations["Teaching Notes and Student Outreach"],
        )

        # The short name is common prose, so only replace it when it is a
        # standalone element value or an exact title attribute.
        short_title = translations["Teaching Notes"]
        content = re.sub(
            r"(?<=>)(\s*)Teaching Notes(\s*)(?=<)",
            lambda match: f"{match.group(1)}{short_title}{match.group(2)}",
            content,
        )
        content = re.sub(
            r"(\btitle\s*=\s*['\"])Teaching Notes(['\"])",
            lambda match: f"{match.group(1)}{short_title}{match.group(2)}",
            content,
            flags=re.IGNORECASE,
        )
        return content

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
                
            if target_count > (en_count + 5): return True
            return False
        except Exception:
            return False

    def _extract_page_title(self, content: str, ext: str) -> str:
        try:
            if ext in ["html", "xml", "qti"]:
                soup = BeautifulSoup(content, 'xml' if ext in ['xml', 'qti'] else 'html.parser')
                edtech_title = soup.find(id='edtech-meta-title')
                if edtech_title and edtech_title.get_text(strip=True):
                    return edtech_title.get_text(strip=True)
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

        if ext == "html" and self.target_language == "PTBR":
            with open(target_filepath, "r", encoding="utf-8") as f:
                possible_attention_content = f.read()
            if self._is_attention_messaging_page(
                target_filepath,
                possible_attention_content,
            ):
                # process_directory() prepares this before concurrent work. The
                # extra call keeps direct --file processing safe and idempotent.
                self._prepare_attention_messaging_package()
                translated_content = self._build_attention_messaging_page(
                    possible_attention_content
                )
                BeautifulSoup(translated_content, "html.parser")
                self._log(
                    "Saving canonical Portuguese attention-page content to "
                    f"{target_filepath}"
                )
                with open(target_filepath, "w", encoding="utf-8") as f:
                    f.write(translated_content)
                self._log("Translation complete for this file.")
                self._log(
                    f"[System] TranslatedPage: {self.ATTENTION_PAGE_PTBR_TITLE} | "
                    f"{filepath}"
                )
                return
            
        is_setup_notes = "setup-notes" in target_filepath.lower()
        is_teaching_notes = self._is_teaching_notes_page(target_filepath)
        if is_setup_notes:
            self._log(f"Applying custom translation rules for setup notes page: {filepath}")

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

        is_edtech_page = bool(
            ext == "html"
            and BeautifulSoup(original_content, "html.parser").find(id="edtech-meta-title")
        )

        original_content = self.link_processor.clean_pre_translation_links(original_content, target_filepath, self._log)
            
        relevant_glossary = self.auditor.get_relevant_terms(original_content)
        relevant_scriptures = self.scripture_checker.get_scriptures_for_text(original_content)
            
        if is_teaching_notes:
            # Apply teaching notes glossary depending on target language
            if self.target_language == "PTBR":
                custom_glossary = {
                    "Dashboard": "Painel de controle", "Courses": "Cursos", "Calendar": "Calendário", 
                    "Inbox": "Caixa de entrada", "History": "Histórico", "Help": "Ajuda", 
                    "Syllabus": "Programa", "Modules": "Módulos", "Announcements": "Avisos", 
                    "Grades": "Notas", "People": "Pessoas", "Assignments": "Tarefas", 
                    "Discussions": "Fóruns", "Files": "Arquivos", "Outcomes": "Objetivos", 
                    "Pages": "Páginas", "Quizzes": "Testes", "Rubrics": "Rubricas", 
                    "Settings": "Configurações", "Teaching Notes": "Notas de Ensino",
                    "Teaching Notes and Student Outreach": "Plano de Aula e de Contato com Estudantes"
                }
            elif self.target_language == "SPA":
                custom_glossary = {
                    "Dashboard": "Tablero", "Courses": "Cursos", "Calendar": "Calendario", 
                    "Inbox": "Bandeja de entrada", "History": "Historial", "Help": "Ayuda", 
                    "Syllabus": "Programa", "Modules": "Módulos", "Announcements": "Anuncios", 
                    "Grades": "Calificaciones", "People": "Personas", "Assignments": "Tareas", 
                    "Discussions": "Foros", "Files": "Archivos", "Outcomes": "Resultados", 
                    "Pages": "Páginas", "Quizzes": "Exámenes", "Rubrics": "Rúbricas", 
                    "Settings": "Configuraciones", "Teaching Notes": "Notas de enseñanza",
                    "Teaching Notes and Student Outreach": "Notas de enseñanza y contacto con estudiantes"
                }
            else:
                custom_glossary = {}

            if relevant_glossary:
                relevant_glossary.update(custom_glossary)
            else:
                relevant_glossary = custom_glossary

        page_title = self._extract_page_title(original_content, ext)
        if not page_title:
            page_title = os.path.splitext(os.path.basename(filepath))[0]

        if ext in ["xml", "qti"]:
            if self.target_language == "PTBR":
                original_content = re.sub(r'\bMissing\b', 'Não Entregue', original_content)
                original_content = re.sub(r'\bmissing\b', 'não entregue', original_content)
            elif self.target_language == "SPA":
                original_content = re.sub(r'\bMissing\b', 'No Entregado', original_content)
                original_content = re.sub(r'\bmissing\b', 'no entregado', original_content)
            translated_content = bot.translate_xml_content(original_content, relevant_glossary, relevant_scriptures, page_title)
        elif ext == "txt":
            translated_content = bot.translate_txt_content(original_content, relevant_glossary, relevant_scriptures)
        else:
            if is_setup_notes and hasattr(bot, 'set_system_prompt'):
                original_prompt = bot.system_prompt
                custom_prompt = (
                    f"You are an expert HTML translator. For this specific 'setup notes' page, you must translate ONLY the text inside the table cells (<td> and <th> tags). "
                    f"Do NOT translate any headers, titles, or paragraphs outside the tables. "
                    f"Furthermore, instead of replacing the English text in the table cells, you must APPEND the {self.target_language} translation after the English text, separated by ' / ' (e.g., 'Modules / Módulos', 'Due / Prazo de entrega: Day/Dia', 'Available From / Disponível a partir de: N/A'). "
                    f"Keep 'N/A' as is, and translate variables like 'Day' to 'Dia' etc. "
                    f"Do not modify tags or layout. Output strictly the HTML block."
                )
                bot.set_system_prompt(custom_prompt)
                try:
                    translated_content = bot.translate_html_content(original_content, relevant_glossary, relevant_scriptures, page_title)
                finally:
                    bot.set_system_prompt(original_prompt)
            elif is_teaching_notes or is_edtech_page:
                translated_content = bot.translate_html_content_in_chunks(
                    original_content,
                    relevant_glossary,
                    relevant_scriptures,
                    page_title,
                )
            else:
                translated_content = bot.translate_html_content(original_content, relevant_glossary, relevant_scriptures, page_title)

        title_corrected_content = self._enforce_teaching_notes_title(translated_content)
        if title_corrected_content != translated_content:
            self._log(f"[Controller] Enforced translated Teaching Notes title in {os.path.basename(filepath)}")
            translated_content = title_corrected_content
        
        translated_content = self.link_processor.rewrite_church_links(translated_content)
        
        # Post-processing: Programmatically empty the Release Notes section for Teaching Notes pages
        # This enforces the spec requirement rather than relying solely on the LLM prompt
        if is_teaching_notes and ext == "html":
            try:
                soup = BeautifulSoup(translated_content, 'html.parser')
                # Find <details> blocks that contain a <summary> with "Release Notes" (or translated variants)
                release_notes_keywords = ["release notes", "notas de versão", "notas de lanzamiento", "notas de la versión"]
                for details_tag in soup.find_all('details'):
                    summary_tag = details_tag.find('summary')
                    if summary_tag:
                        summary_text = summary_tag.get_text(strip=True).lower()
                        if any(kw in summary_text for kw in release_notes_keywords):
                            # Keep the <summary> but remove all other content inside <details>
                            for child in list(details_tag.children):
                                if child != summary_tag:
                                    child.extract()
                            self._log(f"[Controller] Emptied Release Notes section for {os.path.basename(filepath)}")
                translated_content = str(soup)
            except Exception as e:
                self._log(f"[Controller] Warning: Could not process Release Notes section: {e}")
        
        # Validation Check
        if not translated_content or len(translated_content) < len(original_content) * 0.2:
            self._log(f"[System] Error: Translation for {filepath} returned empty or dangerously short content. Restoring original.")
            with open(target_filepath, "w", encoding="utf-8") as f:
                f.write(original_content)
            return
            
        if ext in ["html", "xml", "qti"]:
            try:
                # Just verifying it parses without crashing
                BeautifulSoup(translated_content, 'xml' if ext in ['xml', 'qti'] else 'html.parser')
            except Exception as e:
                self._log(f"[System] Error: Translation for {filepath} produced invalid markup: {e}. Restoring original.")
                with open(target_filepath, "w", encoding="utf-8") as f:
                    f.write(original_content)
                return
                
        self._log(f"Saving translated content to {target_filepath}")
        with open(target_filepath, "w", encoding="utf-8") as f:
            f.write(translated_content)
            
        self._log("Translation complete for this file.")
        
        self._log(f"[System] TranslatedPage: {page_title} | {filepath}")

    def update_excel_dashboard(
        self,
        report_name=None,
        report_code=None,
        review_pages=None,
        excluded_sheets=None,
    ):
        generator = DashboardGenerator(self.log_filepath, self.hub_dir, self.target_language)
        return generator.generate(
            self._log,
            report_name=report_name,
            report_code=report_code,
            review_pages=review_pages,
            excluded_sheets=excluded_sheets,
        )

    def present_checklist(self):
        print("\n" + "="*60)
        print(" TRANSLATION COMPLETE - POST-IMPORT CHECKLIST ")
        print("="*60)
        print("Please complete the following manual steps in Canvas after importing the translated IMSCC.")
        print("Press Enter to check off each item.\n")
        
        checklist = [
            "Import the translated .imscc course package into Canvas.",
            "Go to Course Settings > Feature Options and DISABLE 'Improved Rubrics' (Rubricas melhoradas / Rúbricas mejoradas).",
            "Go to Gradebook Settings > Late Policies, check 'Automatically apply grade for missing submissions', and set it to 0%.",
            "Remind Jenn Hunter to check the Setup Page.",
            "In Settings, add the Tutoring link to the Sidebar.",
            "Review the Translation Dashboard Report (in the Reports folder) for any warnings or untranslated items."
        ]
        
        for i, item in enumerate(checklist, 1):
            input(f"[ ] {i}. {item}\n    (Press Enter when done)")
            print(f"    ✅ Checked!\n")
            
        print("🎉 All post-translation steps completed! You're good to go!\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Course Translation Hub Controller Bot")
    parser.add_argument("--file", help="Specific file to translate")
    parser.add_argument("--dir", help="Directory folder to process")
    parser.add_argument("--imscc", help="IMSCC course package to process")
    parser.add_argument("--lang", choices=["PTBR", "SPA"], help="Target Language")
    
    args = parser.parse_args()
    
    target_language = args.lang
    if not target_language:
        lang_input = input("Which language would you like to translate to? (Enter 'PTBR' or 'SPA'): ").strip().upper()
        if lang_input in ["PTBR", "SPA"]:
            target_language = lang_input
        else:
            print("Invalid language selected. Defaulting to PTBR.")
            target_language = "PTBR"
            
    controller = TranslationController(target_language=target_language, input_dir=args.dir, imscc_path=args.imscc)
    
    if args.file:
        controller.process_file(args.file)
        controller.update_excel_dashboard()
        controller.present_checklist()
    elif args.dir or args.imscc:
        controller.process_directory()
        controller.update_excel_dashboard()
        controller.present_checklist()
    else:
        print("[Controller] Running in test mode. Please provide --file, --dir, or --imscc to process.")
        print("Example: python controller.py --imscc course.imscc")
