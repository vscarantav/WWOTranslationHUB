import os
import argparse
import zipfile
import shutil
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm
from bots.qa_audit_bot import QAAuditBot

class CourseAuditor:
    def __init__(self, english_imscc, translated_imscc):
        self.english_imscc = english_imscc
        self.translated_imscc = translated_imscc
        self.hub_dir = os.path.dirname(os.path.abspath(__file__))
        self.audit_dir = os.path.join(self.hub_dir, "Courses to Audit")
        
        self.en_dir = os.path.join(self.audit_dir, "temp_en")
        self.pt_dir = os.path.join(self.audit_dir, "temp_pt")
        
        # Use flash as requested
        self.bot = QAAuditBot(model_name="gemini-3.5-flash")
        
    def _extract_imscc(self, path, dest):
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.makedirs(dest)
        with zipfile.ZipFile(path, 'r') as zip_ref:
            zip_ref.extractall(dest)
            
    def _build_manifest_map(self, base_dir):
        manifest_path = os.path.join(base_dir, 'imsmanifest.xml')
        res_map = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'xml')
                    resources = soup.find_all('resource')
                    for res in resources:
                        res_id = res.get('identifier')
                        href = res.get('href')
                        if res_id and href:
                            res_map[res_id] = href
            except Exception as e:
                print(f"Error parsing {manifest_path}: {e}")
        return res_map
        
    def _get_all_translatable_files(self, base_dir):
        files_dict = {}
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith('.html') or file.endswith('.xml'):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, base_dir)
                    files_dict[rel_path] = full_path
        return files_dict

    def run_audit(self):
        print(f"Extracting {self.english_imscc} to temp_en...")
        self._extract_imscc(self.english_imscc, self.en_dir)
        
        print(f"Extracting {self.translated_imscc} to temp_pt...")
        self._extract_imscc(self.translated_imscc, self.pt_dir)
        
        # Build maps
        en_manifest = self._build_manifest_map(self.en_dir)
        pt_manifest = self._build_manifest_map(self.pt_dir)
        
        en_files = self._get_all_translatable_files(self.en_dir)
        pt_files = self._get_all_translatable_files(self.pt_dir)
        
        page_report = []
        links_report = []
        content_report = []
        
        # Match using Manifest IDs + Fallback to relative path
        matched_pairs = [] # (en_rel_path, pt_rel_path, method)
        processed_en = set()
        processed_pt = set()
        
        # 1. Match by Manifest ID
        for res_id, en_href in en_manifest.items():
            if res_id in pt_manifest:
                pt_href = pt_manifest[res_id]
                # Check if they are translatable files
                if en_href in en_files and pt_href in pt_files:
                    matched_pairs.append((en_href, pt_href, f"Manifest ({res_id})"))
                    processed_en.add(en_href)
                    processed_pt.add(pt_href)
                    
        # 2. Match remaining by Relative Path
        for en_rel_path in en_files.keys():
            if en_rel_path not in processed_en:
                if en_rel_path in pt_files and en_rel_path not in processed_pt:
                    matched_pairs.append((en_rel_path, en_rel_path, "Relative Path"))
                    processed_en.add(en_rel_path)
                    processed_pt.add(en_rel_path)
                else:
                    # Missing in PT
                    matched_pairs.append((en_rel_path, None, "Unmatched (EN only)"))
                    processed_en.add(en_rel_path)
                    
        # 3. Add remaining PT files
        for pt_rel_path in pt_files.keys():
            if pt_rel_path not in processed_pt:
                # Extra in PT
                matched_pairs.append((None, pt_rel_path, "Unmatched (PT only)"))
                processed_pt.add(pt_rel_path)
                
        print(f"Auditing {len(matched_pairs)} files...")
        
        for en_rel, pt_rel, match_method in tqdm(matched_pairs, desc="Auditing", unit="file"):
            en_exists = en_rel is not None
            pt_exists = pt_rel is not None
            
            display_path = en_rel if en_rel else pt_rel
            
            status = "Match"
            if en_exists and not pt_exists:
                status = "Missing in Translated"
            elif not en_exists and pt_exists:
                status = "Extra in Translated"
                
            page_report.append({
                "File Path": display_path,
                "Match Method": match_method,
                "English Exists": "Yes" if en_exists else "No",
                "Translated Exists": "Yes" if pt_exists else "No",
                "Status": status
            })
            
            # If both exist, audit contents and links
            if en_exists and pt_exists:
                en_path = en_files[en_rel]
                pt_path = pt_files[pt_rel]
                
                with open(en_path, 'r', encoding='utf-8') as f:
                    en_content = f.read()
                with open(pt_path, 'r', encoding='utf-8') as f:
                    pt_content = f.read()
                    
                # Fix BeautifulSoup parser warning
                parser_type = 'xml' if display_path.endswith('.xml') else 'html.parser'
                
                # Only run LLM audit if there is a reasonable amount of text to avoid empty files / pure structure xmls
                soup_en = BeautifulSoup(en_content, parser_type)
                text_len = len(soup_en.get_text(strip=True))
                
                # Links audit (only for HTML)
                if display_path.endswith('.html'):
                    self._audit_links(display_path, en_content, pt_content, links_report)
                
                # Content audit via LLM (skip if very little text to save API calls)
                if text_len > 10:
                    print(f"  [Auditing via Gemini] {display_path}")
                    discrepancies = self.bot.audit_content(en_content, pt_content)
                    for disc in discrepancies:
                        ordered_disc = {"File Path": display_path, "Match Method": match_method}
                        ordered_disc.update(disc)
                        content_report.append(ordered_disc)
                    
        # Extract course name for output filename
        course_name = "Course"
        base_name = os.path.basename(self.english_imscc)
        if base_name:
            course_name = os.path.splitext(base_name)[0]
            
        out_name = f"Audit_Report_{course_name}.xlsx"
        out_path = os.path.join(self.audit_dir, out_name)
        
        print(f"\nSaving reports to {out_path}...")
        with pd.ExcelWriter(out_path, engine='xlsxwriter') as writer:
            pd.DataFrame(page_report).to_excel(writer, sheet_name="Page by Page report", index=False)
            
            if content_report:
                pd.DataFrame(content_report).to_excel(writer, sheet_name="in page content audits", index=False)
            else:
                pd.DataFrame([{"Message": "Comparison complete: The Portuguese translation perfectly matches the English canon."}]).to_excel(writer, sheet_name="in page content audits", index=False)
                
            if links_report:
                pd.DataFrame(links_report).to_excel(writer, sheet_name="links audit", index=False)
            else:
                pd.DataFrame([{"Message": "Comparison complete: No link discrepancies found."}]).to_excel(writer, sheet_name="links audit", index=False)
                
            # Auto-adjust column widths
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
                if sheet_name == "Page by Page report":
                    worksheet.set_column('A:A', 50)
                    worksheet.set_column('B:E', 20)
                elif sheet_name == "in page content audits":
                    worksheet.set_column('A:A', 30)
                    worksheet.set_column('B:C', 20)
                    worksheet.set_column('D:E', 40)
                    worksheet.set_column('F:F', 25)
                    worksheet.set_column('G:G', 50)
                elif sheet_name == "links audit":
                    worksheet.set_column('A:A', 50)
                    worksheet.set_column('B:B', 50)
                    worksheet.set_column('C:C', 25)
                    
        # Clean up temps
        shutil.rmtree(self.en_dir)
        shutil.rmtree(self.pt_dir)
        print("Audit Complete!")
        
    def _audit_links(self, rel_path, en_content, pt_content, links_report):
        en_soup = BeautifulSoup(en_content, 'html.parser')
        pt_soup = BeautifulSoup(pt_content, 'html.parser')
        
        # Only look at external links (starts with http)
        en_links = [(a.get_text(strip=True), a.get('href')) for a in en_soup.find_all('a', href=True) if str(a.get('href')).startswith('http')]
        pt_links = [(a.get_text(strip=True), a.get('href')) for a in pt_soup.find_all('a', href=True) if str(a.get('href')).startswith('http')]
        
        # Compare sets of URLs
        en_urls = set([href for text, href in en_links])
        pt_urls = set([href for text, href in pt_links])
        
        missing_urls = en_urls - pt_urls
        extra_urls = pt_urls - en_urls
        
        for url in missing_urls:
            links_report.append({
                "File Path": rel_path,
                "URL": url,
                "Issue": "Missing in Translated"
            })
            
        for url in extra_urls:
            links_report.append({
                "File Path": rel_path,
                "URL": url,
                "Issue": "Extra in Translated"
            })

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Course Translation Auditor")
    parser.add_argument("--en", help="Path to English IMSCC")
    parser.add_argument("--pt", help="Path to Translated IMSCC")
    args = parser.parse_args()
    
    hub_dir = os.path.dirname(os.path.abspath(__file__))
    audit_dir = os.path.join(hub_dir, "Courses to Audit")
    
    # Ensure audit dir exists
    if not os.path.exists(audit_dir):
        os.makedirs(audit_dir)
    
    en_imscc = args.en
    pt_imscc = args.pt
    
    # Auto-detect if not provided
    if not en_imscc or not pt_imscc:
        imsccs = [f for f in os.listdir(audit_dir) if f.endswith('.imscc')]
        if len(imsccs) == 2:
            # Assume one is PT or ES
            if 'PTBR' in imsccs[0] or 'ES' in imsccs[0] or 'translated' in imsccs[0].lower():
                pt_imscc = os.path.join(audit_dir, imsccs[0])
                en_imscc = os.path.join(audit_dir, imsccs[1])
            else:
                en_imscc = os.path.join(audit_dir, imsccs[0])
                pt_imscc = os.path.join(audit_dir, imsccs[1])
        else:
            print("Could not auto-detect IMSCC files.")
            print(f"Please place exactly two .imscc files in '{audit_dir}' or use --en and --pt arguments.")
            exit(1)
            
    if not os.path.exists(en_imscc):
        print(f"Error: {en_imscc} not found.")
        exit(1)
        
    if not os.path.exists(pt_imscc):
        print(f"Error: {pt_imscc} not found.")
        exit(1)
                
    auditor = CourseAuditor(en_imscc, pt_imscc)
    auditor.run_audit()
