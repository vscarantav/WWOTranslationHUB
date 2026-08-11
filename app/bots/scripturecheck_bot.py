import json
import os
import re

class ScriptureCheckBot:
    def __init__(self, target_language="PTBR", hub_dir=None):
        self.target_language = target_language
        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.hub_dir = hub_dir or os.path.dirname(self.app_dir)
        
        self.log_filepath = os.path.join(self.app_dir, "bots", "translation_log.txt")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"\n--- New ScriptureCheckBot Session (Target: {self.target_language}) ---\n")
            
        self.lang_folder = "por" if self.target_language.upper() == "PTBR" else "spa"
        self.scriptures_path = os.path.join(self.hub_dir, "Glossary", "scriptures", self.lang_folder)

    def _log(self, message: str):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def _extract_references(self, original_content: str) -> list:
        # Regex to match:
        # Book names (1 Nephi, D&C, etc) followed by Chapter:Verse(s)
        # e.g. 1 Nephi 3:7, D&C 8:2-3, Moses 1:39
        
        books = [
            r"1\s*Nephi", r"2\s*Nephi", r"Jacob", r"Enos", r"Jarom", r"Omni", r"Words\s*of\s*Mormon",
            r"Mosiah", r"Alma", r"Helaman", r"3\s*Nephi", r"4\s*Nephi", r"Mormon", r"Ether", r"Moroni",
            r"D&C", r"Doctrine\s*and\s*Covenants",
            r"Moses", r"Abraham", r"Joseph\s*Smith\s*[—-]\s*Matthew", r"Joseph\s*Smith\s*[—-]\s*History", r"Articles\s*of\s*Faith"
        ]
        book_pattern = "|".join(books)
        
        # Matches Book Chapter:Verse(s)
        # e.g. 1 Nephi 3:7 or 1 Nephi 3:7-8 or 1 Nephi 3:7, 9
        pattern = r"(?i)\b(" + book_pattern + r")\s+(\d+)\s*:\s*(\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)"
        
        matches = re.findall(pattern, original_content)
        references = []
        
        for match in matches:
            book_str = match[0].strip().title()
            chapter = match[1].strip()
            verses_str = match[2].strip()
            
            # Map book_str to volume and slug
            volume, slug = self._map_book_to_slug(book_str)
            if not volume or not slug:
                continue
                
            # Parse verses
            verses = self._parse_verses(verses_str)
            
            references.append({
                "volume": volume,
                "book": slug,
                "chapter": chapter,
                "verses": verses,
                "original_match": f"{book_str} {chapter}:{verses_str}"
            })
            
        return references

    def _parse_verses(self, verses_str: str) -> list:
        # e.g., "7-8, 10" -> ["7", "8", "10"]
        verses = []
        parts = re.split(r",\s*", verses_str)
        for part in parts:
            if "-" in part:
                start, end = part.split("-")
                try:
                    start_num = int(start.strip())
                    end_num = int(end.strip())
                    for i in range(start_num, end_num + 1):
                        verses.append(str(i))
                except ValueError:
                    pass
            else:
                verses.append(part.strip())
        return verses

    def _map_book_to_slug(self, book_str: str):
        bs = book_str.lower().replace(" ", "")
        
        bom_map = {
            "1nephi": "1-ne", "2nephi": "2-ne", "jacob": "jacob", "enos": "enos",
            "jarom": "jarom", "omni": "omni", "wordsofmormon": "w-of-m",
            "mosiah": "mosiah", "alma": "alma", "helaman": "hel",
            "3nephi": "3-ne", "4nephi": "4-ne", "mormon": "morm",
            "ether": "ether", "moroni": "moro"
        }
        
        dc_map = {
            "d&c": "dc", "doctrineandcovenants": "dc"
        }
        
        pgp_map = {
            "moses": "moses", "abraham": "abr",
            "josephsmith-matthew": "js-m", "josephsmith—matthew": "js-m",
            "josephsmith-history": "js-h", "josephsmith—history": "js-h",
            "articlesoffaith": "a-of-f"
        }
        
        if bs in bom_map:
            return "bookofmormon", bom_map[bs]
        if bs in dc_map:
            return "doctrineandcovenants", dc_map[bs]
        if bs in pgp_map:
            return "pearlofgreatprice", pgp_map[bs]
            
        return None, None

    def _lookup_scriptures(self, references: list) -> dict:
        results = {}
        for ref in references:
            volume = ref.get("volume")
            book = ref.get("book")
            chapter = str(ref.get("chapter"))
            verses = [str(v) for v in ref.get("verses", [])]
            orig_match = ref.get("original_match")
            
            if not volume or not chapter or not verses:
                continue
                
            json_file = os.path.join(self.scriptures_path, f"{volume}.json")
            if not os.path.exists(json_file):
                self._log(f"[ScriptureCheckBot] JSON file not found: {json_file}")
                continue
                
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                for verse in verses:
                    verse_text = None
                    try:
                        if volume == "doctrineandcovenants":
                            verse_text = data[chapter]["verses"][verse]
                        elif volume == "bookofmormon":
                            verse_text = data[book]["chapters"][chapter][verse]
                        elif volume == "pearlofgreatprice":
                            verse_text = data[book]["chapters"][chapter][verse]
                    except KeyError:
                        self._log(f"[ScriptureCheckBot] Verse {verse} not found in {volume} {book} {chapter}")
                        continue
                        
                    if verse_text:
                        # Map the original reference string to its target translation
                        key = f"{orig_match} (Verse {verse})"
                        results[key] = verse_text
            except Exception as e:
                self._log(f"[ScriptureCheckBot] Error reading {json_file}: {e}")
                
        return results

    def get_scriptures_for_text(self, original_content: str) -> dict:
        keywords = [
            "nephi", "jacob", "enos", "jarom", "omni", "mosiah", "alma", "helaman", 
            "mormon", "ether", "moroni", "d&c", "doctrine and covenants", 
            "moses", "abraham"
        ]
        
        text_lower = original_content.lower()
        if not any(kw in text_lower for kw in keywords):
            return {}
            
        references = self._extract_references(original_content)
        if not references:
            return {}
            
        self._log(f"[ScriptureCheckBot] Found references via regex: {references}")
        scriptures_data = self._lookup_scriptures(references)
        
        if scriptures_data:
            self._log(f"[ScriptureCheckBot] Looked up {len(scriptures_data)} verses.")
            
        return scriptures_data
