import os
import re
import shutil
import tempfile
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
        self.canvas_url = None
        self.source_course_id = None
        self.source_course_id_source = None
        self.source_course_id_candidates = []

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

            # Every translation run starts from the selected archive. Reusing a
            # directory from an earlier archive with the same filename can mix
            # old course metadata and content into the new run.
            staging_dir = tempfile.mkdtemp(prefix=f".{root_dir}-", dir=courses_dir)
            try:
                print(f"[WorkspaceManager] Extracting {self.imscc_path} to {self.original_dir}")
                with zipfile.ZipFile(self.imscc_path, 'r') as zip_ref:
                    zip_ref.extractall(staging_dir)

                if os.path.exists(self.original_dir):
                    shutil.rmtree(self.original_dir)
                shutil.move(staging_dir, self.original_dir)
                staging_dir = None
            finally:
                if staging_dir and os.path.exists(staging_dir):
                    shutil.rmtree(staging_dir)
        else:
            if self.input_dir:
                root_dir = self.input_dir
            else:
                root_dir = root_directory_default
                
            self.original_dir = os.path.join(courses_dir, root_dir)
            
        self.output_dir = f"{self.original_dir}_{self.target_language}"

        if self.imscc_path and os.path.exists(self.output_dir):
            print(f"[WorkspaceManager] Refreshing workspace: {self.output_dir}")
            shutil.rmtree(self.output_dir)

        if not os.path.exists(self.output_dir):
            if os.path.exists(self.original_dir):
                print(f"[WorkspaceManager] Creating workspace: {self.output_dir}")
                shutil.copytree(self.original_dir, self.output_dir)
            else:
                print(f"[WorkspaceManager] WARNING: Original directory {self.original_dir} not found.")
                return False
        return True

    def _read_source_text(self, relative_path):
        """Read package content directly from the IMSCC when one is available."""
        normalized_path = relative_path.replace('\\', '/')
        if self.imscc_path and zipfile.is_zipfile(self.imscc_path):
            with zipfile.ZipFile(self.imscc_path, 'r') as archive:
                members = archive.namelist()
                member = next(
                    (name for name in members if name.rstrip('/') == normalized_path),
                    None,
                )
                if member is None:
                    suffix = f"/{normalized_path}"
                    matches = [name for name in members if name.endswith(suffix)]
                    if len(matches) == 1:
                        member = matches[0]
                if member is not None:
                    return archive.read(member).decode('utf-8-sig')
            return None

        if not self.original_dir:
            return None
        path = os.path.join(self.original_dir, *normalized_path.split('/'))
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8-sig') as source_file:
            return source_file.read()

    def _iter_wiki_source_html(self):
        """Yield wiki HTML from the archive itself, falling back to the workspace."""
        if self.imscc_path and zipfile.is_zipfile(self.imscc_path):
            with zipfile.ZipFile(self.imscc_path, 'r') as archive:
                for member in archive.namelist():
                    normalized = member.replace('\\', '/')
                    if '/wiki_content/' in f"/{normalized}" and normalized.lower().endswith('.html'):
                        try:
                            yield normalized, archive.read(member).decode('utf-8-sig')
                        except (KeyError, UnicodeDecodeError):
                            continue
            return

        if not self.original_dir:
            return
        wiki_dir = os.path.join(self.original_dir, 'wiki_content')
        if not os.path.exists(wiki_dir):
            return
        for filename in os.listdir(wiki_dir):
            if not filename.lower().endswith('.html'):
                continue
            try:
                with open(os.path.join(wiki_dir, filename), 'r', encoding='utf-8-sig') as source_file:
                    yield filename, source_file.read()
            except (OSError, UnicodeDecodeError):
                continue

    def extract_course_info(self, _log_func):
        self.canvas_url = None
        self.source_course_id = None
        self.source_course_id_source = None
        self.source_course_id_candidates = []
        course_name = "Unknown Course"
        course_code = "UNKNOWN"
        manifest_content = self._read_source_text('imsmanifest.xml')
        if manifest_content:
            try:
                soup = BeautifulSoup(manifest_content, 'xml')
                title_tag = soup.find('lom:title') or soup.find('title')
                if title_tag:
                    string_tag = title_tag.find('lom:string') or title_tag.find('string')
                    if string_tag:
                        course_name = string_tag.text.strip()
                    else:
                        course_name = title_tag.text.strip()
            except Exception:
                pass

        settings_content = self._read_source_text('course_settings/course_settings.xml')
        if settings_content:
            try:
                soup = BeautifulSoup(settings_content, 'xml')
                code_tag = soup.find('course_code')
                if code_tag:
                    course_code = code_tag.text.strip()
                title_tag = soup.find('title')
                if title_tag and course_name == "Unknown Course":
                    course_name = title_tag.text.strip()
            except Exception:
                pass

        context_content = self._read_source_text('course_settings/context.xml')
        if context_content:
            try:
                soup = BeautifulSoup(context_content, 'xml')
                domain_tag = soup.find('canvas_domain')
                if domain_tag and domain_tag.text.strip():
                    self.canvas_url = f"https://{domain_tag.text.strip()}"

                # context.xml identifies the course that Canvas actually
                # exported. Embedded wiki endpoints may point at assets copied
                # from any number of other courses and are not authoritative.
                course_id_tag = soup.find('course_id')
                if course_id_tag:
                    context_course_id = course_id_tag.text.strip()
                    if context_course_id.isdigit():
                        self.source_course_id = context_course_id
                        self.source_course_id_source = 'context.xml'
            except Exception:
                pass

        # Legacy fallback: accept embedded endpoints only when every endpoint
        # agrees on one course. Never let filesystem ordering choose an ID.
        endpoint_ids = set()
        endpoint_pattern = re.compile(
            r'data-api-endpoint\s*=\s*["\'][^"\']+/api/v1/courses/(\d+)(?:/|["\'])',
            re.IGNORECASE,
        )
        for _filename, content in self._iter_wiki_source_html():
            endpoint_ids.update(endpoint_pattern.findall(content))
        self.source_course_id_candidates = sorted(endpoint_ids, key=int)

        if self.source_course_id is None and len(endpoint_ids) == 1:
            self.source_course_id = next(iter(endpoint_ids))
            self.source_course_id_source = 'wiki endpoints'
        elif self.source_course_id is None and len(endpoint_ids) > 1:
            _log_func(
                "[WorkspaceManager] WARNING: Multiple course IDs were found in wiki "
                "endpoints; the entered EN Master URL will be used instead: "
                + ", ".join(self.source_course_id_candidates)
            )

        _log_func(f"[System] CourseInfo: {course_name}|{course_code}")
        if self.canvas_url:
            _log_func(f"[System] Canvas URL: {self.canvas_url}")
        if self.source_course_id:
            _log_func(
                f"[System] Source Course ID: {self.source_course_id} "
                f"({self.source_course_id_source})"
            )

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
        
        # Verify structure before zipping: imsmanifest.xml MUST be at root
        manifest_path = os.path.join(self.output_dir, 'imsmanifest.xml')
        if not os.path.exists(manifest_path):
            # Check if it was nested one level deep
            subdirs = [os.path.join(self.output_dir, d) for d in os.listdir(self.output_dir) if os.path.isdir(os.path.join(self.output_dir, d))]
            if len(subdirs) == 1:
                nested_manifest = os.path.join(subdirs[0], 'imsmanifest.xml')
                if os.path.exists(nested_manifest):
                    _log_func("[WorkspaceManager] WARNING: Nested directory structure detected. Correcting for IMSCC...")
                    # The archive root should be the nested folder
                    zip_path = shutil.make_archive(self.output_dir, 'zip', subdirs[0])
                else:
                    _log_func("[WorkspaceManager] ERROR: imsmanifest.xml not found. Resulting IMSCC may be invalid.")
                    zip_path = shutil.make_archive(self.output_dir, 'zip', self.output_dir)
            else:
                _log_func("[WorkspaceManager] ERROR: imsmanifest.xml not found. Resulting IMSCC may be invalid.")
                zip_path = shutil.make_archive(self.output_dir, 'zip', self.output_dir)
        else:
            zip_path = shutil.make_archive(self.output_dir, 'zip', self.output_dir)
            
        imscc_path = self.output_dir + ".imscc"
        if os.path.exists(imscc_path):
            os.remove(imscc_path)
            
        os.rename(zip_path, imscc_path)
        
        msg = f"Successfully created course package: {imscc_path}"
        print(f"[WorkspaceManager] {msg}")
        _log_func(msg)
