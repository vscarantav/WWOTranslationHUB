import os
import shutil
import zipfile
import collections
from bs4 import BeautifulSoup

class WorkspaceManager:
    def __init__(self, target_language: str, hub_dir: str, input_dir=None, imscc_path=None):
        self.target_language = target_language
        self.hub_dir = hub_dir
        self.input_dir = input_dir
        self.imscc_path = imscc_path
        self.original_dir = None
        self.output_dir = None
        self.filepaths = []

    def setup_workspace(self, root_directory_default: str):
        courses_dir = os.path.join(self.hub_dir, "Courses to Translate")
        if not os.path.exists(courses_dir):
            os.makedirs(courses_dir)

        if self.imscc_path:
            if not os.path.isabs(self.imscc_path) and not os.path.exists(self.imscc_path):
                alt_path = os.path.join(courses_dir, self.imscc_path)
                if os.path.exists(alt_path):
                    self.imscc_path = alt_path

            if not os.path.exists(self.imscc_path):
                print(f"[WorkspaceManager] WARNING: IMSCC file {self.imscc_path} not found.")
                return False
            
            base_name = os.path.basename(self.imscc_path)
            root_dir = os.path.splitext(base_name)[0]
            self.original_dir = os.path.join(courses_dir, root_dir)
            
            if not os.path.exists(self.original_dir):
                print(f"[WorkspaceManager] Extracting {self.imscc_path} to {self.original_dir}")
                with zipfile.ZipFile(self.imscc_path, 'r') as zip_ref:
                    zip_ref.extractall(self.original_dir)
        else:
            if self.input_dir:
                root_dir = self.input_dir
            else:
                root_dir = root_directory_default
                
            self.original_dir = os.path.join(courses_dir, root_dir)
            
        self.output_dir = f"{self.original_dir}_{self.target_language}"
        
        if not os.path.exists(self.output_dir):
            if os.path.exists(self.original_dir):
                print(f"[WorkspaceManager] Creating workspace: {self.output_dir}")
                shutil.copytree(self.original_dir, self.output_dir)
            else:
                print(f"[WorkspaceManager] WARNING: Original directory {self.original_dir} not found.")
                return False
        return True

    def extract_course_info(self, _log_func):
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
            except Exception:
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
            except Exception:
                pass

        _log_func(f"[System] CourseInfo: {course_name}|{course_code}")

    def collect_files(self, _log_func) -> list:
        file_counts = collections.defaultdict(int)
        self.filepaths = []
        for root, dirs, files in os.walk(self.output_dir):
            for file in files:
                self.filepaths.append(os.path.join(root, file))
                ext = file.split('.')[-1].lower() if '.' in file else 'unknown'
                file_counts[ext] += 1
                
        for ext, count in file_counts.items():
            _log_func(f"[System] FileTypeCount: {ext}|{count}")
            
        return self.filepaths

    def get_target_filepath(self, filepath: str) -> str:
        filepath_abs = os.path.abspath(filepath)
        if filepath_abs.startswith(self.output_dir + os.sep):
            return filepath_abs
        elif filepath_abs.startswith(self.original_dir + os.sep) or filepath_abs == self.original_dir:
            rel_path = os.path.relpath(filepath_abs, self.original_dir)
            return os.path.join(self.output_dir, rel_path)
        return filepath_abs

    def compress_to_imscc(self, _log_func):
        msg = "Compressing translated directory to IMSCC format..."
        print(f"\n[WorkspaceManager] {msg}")
        _log_func(msg)
        
        zip_path = shutil.make_archive(self.output_dir, 'zip', self.output_dir)
        imscc_path = self.output_dir + ".imscc"
        if os.path.exists(imscc_path):
            os.remove(imscc_path)
            
        os.rename(zip_path, imscc_path)
        
        msg = f"Successfully created course package: {imscc_path}"
        print(f"[WorkspaceManager] {msg}")
        _log_func(msg)
