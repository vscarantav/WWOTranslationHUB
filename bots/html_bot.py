import os
import json
import re
import uuid
from bs4 import BeautifulSoup
import google.generativeai as genai  # type: ignore

class HTMLTranslationBot:
    def __init__(self, api_key=None, target_language="PTBR"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.client_ready = True
        else:
            self.client_ready = False
            
        self.target_language = target_language
        self.model = genai.GenerativeModel("gemini-3.5-flash")
        self.system_prompt = self._get_system_prompt()
        
        self.log_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New HTMLBot Session (Target: {self.target_language}) ---\n")

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def _get_system_prompt(self):
        return f"You are an expert HTML translator. Translate text into {self.target_language}. Do not modify tags or layout. Output strictly the translated HTML block. Do not translate URLs, UUID placeholders, or internal variable names."

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    def translate_html_content(self, html_content: str, relevant_glossary: dict = None, relevant_scriptures: dict = None) -> str:
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

            return output
        except Exception as e:
            msg = f"[HTMLBot] Error during translation: {e}"
            print(msg)
            self._log(msg)
            return html_content

    def process_file(self, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        msg = f"[HTMLBot] Translating {filepath} to {self.target_language}..."
        print(msg)
        self._log(msg)

        relevant_glossary = None
        if "teaching-notes-and-student-outreach" in filepath.lower():
            relevant_glossary = {
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
                "Student Outreach": "Acompanhamento de Estudantes (or Contato com Estudantes)",
                "Non-participating and Failing Students": "Estudantes não participantes e ausentes",
                "Missing Assignments": "Tarefas Incompletas",
                "Low Performing Students": "Estudantes com baixo desempenho",
                "Positive Outreach": "Acompanhamento com feedback positivo",
                "Inspired Outreach": "Acompanhamento específico inspirado"
            }

        translated_content = self.translate_html_content(content, relevant_glossary=relevant_glossary)
        return translated_content
