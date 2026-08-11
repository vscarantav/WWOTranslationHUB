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
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.hub_dir = os.path.dirname(self.app_dir)
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
        
    def _clean_text(self, text):
        if isinstance(text, str):
            text = text.replace('`', '')
            text = text.replace('**', '')
            text = text.replace('*', '')
            # Strip out any remaining html tags and unescape entities
            return BeautifulSoup(text, 'html.parser').get_text(separator=' ', strip=True)
        return text

    def _build_title_map(self, base_dir):
        manifest_path = os.path.join(base_dir, 'imsmanifest.xml')
        href_to_title = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'xml')
                    
                    id_to_title = {}
                    items = soup.find_all('item')
                    for item in items:
                        ref = item.get('identifierref')
                        title_tag = item.find('title', recursive=False)
                        if ref and title_tag:
                            id_to_title[ref] = title_tag.get_text(strip=True)
                            
                    resources = soup.find_all('resource')
                    for res in resources:
                        res_id = res.get('identifier')
                        title = id_to_title.get(res_id)
                        if title:
                            files = res.find_all('file')
                            for file_tag in files:
                                href = file_tag.get('href')
                                if href:
                                    href_to_title[href] = title
            except Exception as e:
                print(f"Error parsing titles from {manifest_path}: {e}")
        return href_to_title

    def _get_file_title(self, full_path):
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                soup = BeautifulSoup(content, 'xml' if full_path.endswith('.xml') else 'html.parser')
                
                title_tag = soup.find('title')
                if title_tag and title_tag.get_text(strip=True):
                    return title_tag.get_text(strip=True)
                    
                title_attr_tag = soup.find(lambda tag: tag.has_attr('title'))
                if title_attr_tag and title_attr_tag.get('title'):
                    return title_attr_tag.get('title').strip()
        except:
            pass
            
        try:
            dir_name = os.path.dirname(full_path)
            for meta_name in ['assessment_meta.xml', 'assignment_settings.xml', 'discussion_topic_meta.xml']:
                meta_file = os.path.join(dir_name, meta_name)
                if os.path.exists(meta_file) and full_path != meta_file:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        soup = BeautifulSoup(f.read(), 'xml')
                        title_tag = soup.find('title')
                        if title_tag and title_tag.get_text(strip=True):
                            return title_tag.get_text(strip=True)
        except:
            pass
            
        return os.path.basename(full_path)
        
    def _get_all_translatable_files(self, base_dir):
        files_dict = {}
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith('.html') or file.endswith('.xml'):
                    if file == "imsmanifest.xml":
                        continue
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
        
        en_titles = self._build_title_map(self.en_dir)
        pt_titles = self._build_title_map(self.pt_dir)
        
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
                    
        # 3. Match remaining via AI Pairing (for W03 -> S03 rename scenarios)
        unmatched_en_titles = {}
        for en_rel_path in en_files.keys():
            if en_rel_path not in processed_en:
                unmatched_en_titles[en_rel_path] = en_titles.get(en_rel_path) or self._get_file_title(en_files[en_rel_path])
                
        unmatched_pt_titles = {}
        for pt_rel_path in pt_files.keys():
            if pt_rel_path not in processed_pt:
                unmatched_pt_titles[pt_rel_path] = pt_titles.get(pt_rel_path) or self._get_file_title(pt_files[pt_rel_path])
                
        if unmatched_en_titles and unmatched_pt_titles:
            print(f"  [AI] Pairing {len(unmatched_en_titles)} unmatched EN files with {len(unmatched_pt_titles)} PT files...")
            paired_files = self.bot.pair_unmatched_files(unmatched_en_titles, unmatched_pt_titles)
            for en_rel, pt_rel in paired_files.items():
                if en_rel in unmatched_en_titles and pt_rel in unmatched_pt_titles:
                    matched_pairs.append((en_rel, pt_rel, "AI Pairing"))
                    processed_en.add(en_rel)
                    processed_pt.add(pt_rel)
                    
        # 4. Add remaining EN files as Missing
        for en_rel_path in en_files.keys():
            if en_rel_path not in processed_en:
                matched_pairs.append((en_rel_path, None, "Unmatched (EN only)"))
                processed_en.add(en_rel_path)
                    
        # 5. Add remaining PT files as Extra
        for pt_rel_path in pt_files.keys():
            if pt_rel_path not in processed_pt:
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
                
            en_title = en_titles.get(en_rel, "N/A") if en_rel else "N/A"
            pt_title = pt_titles.get(pt_rel, "N/A") if pt_rel else "N/A"
            
            if en_title in (None, "N/A", "") and en_exists:
                en_title = self._get_file_title(en_files[en_rel])
            if pt_title in (None, "N/A", "") and pt_exists:
                pt_title = self._get_file_title(pt_files[pt_rel])
                
            page_report.append({
                "Page Name (EN)": en_title,
                "Page Name (PT)": pt_title,
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
                    self._audit_links(en_title, pt_title, display_path, en_content, pt_content, links_report)
                
                # Content audit via LLM (skip if very little text to save API calls)
                if text_len > 10:
                    print(f"  [Auditing via Gemini] {display_path}")
                    discrepancies = self.bot.audit_content(en_content, pt_content)
                    for disc in discrepancies:
                        ordered_disc = {
                            "Page Name (EN)": en_title, 
                            "Page Name (PT)": pt_title
                        }
                        for k, v in disc.items():
                            ordered_disc[k] = self._clean_text(v)
                        content_report.append(ordered_disc)
                    
        # Extract course name for output filename
        course_name = "Course"
        base_name = os.path.basename(self.english_imscc)
        if base_name:
            course_name = os.path.splitext(base_name)[0]
            
        out_name = f"Audit_Report_{course_name}.xlsx"
        reports_dir = os.path.join(self.hub_dir, "Reports")
        os.makedirs(reports_dir, exist_ok=True)
        out_path = os.path.join(reports_dir, out_name)
        
        print(f"\nSaving reports to {out_path}...")
        
        df_page = pd.DataFrame(page_report)
        df_content = pd.DataFrame(content_report) if content_report else pd.DataFrame([{"Message": "Comparison complete: The Portuguese translation perfectly matches the English canon."}])
        df_links = pd.DataFrame(links_report) if links_report else pd.DataFrame([{"Message": "Comparison complete: No link discrepancies found."}])
        
        with pd.ExcelWriter(out_path, engine='xlsxwriter') as writer:
            df_page.to_excel(writer, sheet_name="Page Audit Report", index=False)
            df_content.to_excel(writer, sheet_name="Content Audit Report", index=False)
            df_links.to_excel(writer, sheet_name="Links Audit Reports", index=False)
                
            # Formatting
            for sheet_name, df in [("Page Audit Report", df_page), 
                                   ("Content Audit Report", df_content), 
                                   ("Links Audit Reports", df_links)]:
                worksheet = writer.sheets[sheet_name]
                
                # Apply autofilter
                max_row, max_col = df.shape
                if max_col > 0:
                    worksheet.autofilter(0, 0, max_row, max_col - 1)
                
                # Auto-adjust column widths
                if sheet_name == "Page Audit Report":
                    worksheet.set_column('A:B', 40)
                    worksheet.set_column('C:E', 20)
                elif sheet_name == "Content Audit Report":
                    worksheet.set_column('A:C', 30)
                    worksheet.set_column('D:E', 40)
                    worksheet.set_column('F:F', 25)
                    worksheet.set_column('G:G', 50)
                elif sheet_name == "Links Audit Reports":
                    worksheet.set_column('A:B', 30)
                    worksheet.set_column('C:C', 50)
                    worksheet.set_column('D:D', 25)
                    
        # Clean up temps
        shutil.rmtree(self.en_dir)
        shutil.rmtree(self.pt_dir)
        print("Audit Complete!")
        
    def _audit_links(self, en_title, pt_title, rel_path, en_content, pt_content, links_report):
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
                "Page Name (EN)": en_title,
                "Page Name (PT)": pt_title,
                "URL": url,
                "Issue": "Missing in Translated"
            })
            
        for url in extra_urls:
            links_report.append({
                "Page Name (EN)": en_title,
                "Page Name (PT)": pt_title,
                "URL": url,
                "Issue": "Extra in Translated"
            })

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Course Translation Auditor")
    parser.add_argument("--en", help="Path to English IMSCC")
    parser.add_argument("--pt", help="Path to Translated IMSCC")
    args = parser.parse_args()
    
    app_dir = os.path.dirname(os.path.abspath(__file__))
    hub_dir = os.path.dirname(app_dir)
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
