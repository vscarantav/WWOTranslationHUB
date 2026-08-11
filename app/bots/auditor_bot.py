import json
import os
import re

class GlossaryAuditBot:
    def __init__(self, target_language="PTBR", hub_dir=None):
        self.target_language = target_language
        self.hub_dir = hub_dir or os.getcwd()
        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.log_filepath = os.path.join(self.app_dir, "bots", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New AuditorBot Session (Target: {self.target_language}) ---\n")
            
        self.glossary = self._load_glossary()

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def _load_glossary(self) -> dict:
        self.glossary_path = os.path.join(
            self.hub_dir, 
            "Glossary",
            "glossary_ptbr.json" 
            if self.target_language == "PTBR" 
            else "glossary_es.json"
        )
        filepath = self.glossary_path

        if not os.path.exists(filepath):
            msg = f"[AuditorBot] Warning: Glossary file {filepath} not found."
            print(msg)
            self._log(msg)
            return {}

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_relevant_terms(self, original_content: str) -> dict:
        """
        Scans the original English content and returns a subset of the glossary
        containing only the terms that appear in the text.
        """
        if not self.glossary:
            return {}
            
        relevant_terms = {}
        content_lower = original_content.lower()
        
        for eng_term, trans_term in self.glossary.items():
            # A simple substring check works well for English terms in our glossary
            if eng_term.lower() in content_lower:
                relevant_terms[eng_term] = trans_term
                
        if relevant_terms:
            msg = f"[AuditorBot] Found {len(relevant_terms)} relevant glossary terms in text."
            self._log(msg)
                
        return relevant_terms
