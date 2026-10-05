import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from bs4 import BeautifulSoup

from bots.html_bot import HTMLTranslationBot
from bots.image_bot import ImageProcessorBot
from bots.markdown_bot import MarkdownTranslationBot
from bots.scripturecheck_bot import ScriptureCheckBot
from bots.txt_bot import TextTranslationBot
from bots.variable_extraction import VariableAnalysisBot
from bots.xml_bot import XMLTranslationBot
from core.github_content_validator import GitHubContentValidator
from core.github_report_generator import GitHubTranslationReportGenerator
from core.github_repository_manager import GitHubRepositoryManager
from core.github_repository_scanner import GitHubRepositoryScanner
from core.sd_glossary import SoftwareDevelopmentGlossary


@dataclass
class GitHubTranslationResult:
    repository_url: str
    pages_url: str
    report_path: str
    workspace_path: str
    repository_name: str


class GitHubTranslationRunError(RuntimeError):
    def __init__(self, message, report_path="", workspace_path=""):
        super().__init__(message)
        self.report_path = report_path
        self.workspace_path = workspace_path


class GitHubTranslationController:
    """Translate a cloned repository and publish only to a new personal repo."""

    def __init__(
        self,
        hub_dir,
        token,
        target_language="PTBR",
        *,
        repository_manager=None,
        scanner=None,
        validator=None,
        report_generator=None,
        bot_factory=None,
        max_workers=3,
        log_func=print,
    ):
        self.hub_dir = Path(hub_dir).resolve()
        self.target_language = target_language.upper()
        if self.target_language != "PTBR":
            raise ValueError("GitHub translation currently supports Portuguese (PTBR) only.")
        self.log = log_func
        self._log_lock = threading.Lock()
        self._log_filepath = self.hub_dir / "app" / "bots" / "translation_log.txt"
        self._log_filepath.parent.mkdir(parents=True, exist_ok=True)
        self._log_filepath.write_text(
            "--- New GitHub Translation Session (Target: PTBR) ---\n",
            encoding="utf-8",
        )
        self.max_workers = max_workers
        self.repository_manager = repository_manager or GitHubRepositoryManager(token, log_func=self._log)
        self.scanner = scanner or GitHubRepositoryScanner()
        self.validator = validator or GitHubContentValidator()
        self.report_generator = report_generator or GitHubTranslationReportGenerator(self.hub_dir / "Reports")
        self.bot_factory = bot_factory

    def _log(self, message):
        with self._log_lock:
            with self._log_filepath.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{message}\n")
            self.log(message)

    @staticmethod
    def _safe_workspace_name(owner, repository):
        value = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{owner}-{repository}")
        return value.strip("-.") or "github-translation"

    def _create_workspace(self, owner, repository):
        parent = self.hub_dir / "github_workspace"
        parent.mkdir(parents=True, exist_ok=True)
        base = self._safe_workspace_name(owner, repository)
        candidate = parent / base
        number = 2
        while candidate.exists():
            candidate = parent / f"{base}-{number}"
            number += 1
        candidate.mkdir()
        return candidate

    def _bots(self):
        if self.bot_factory:
            return self.bot_factory()
        api_key = os.environ.get("GEMINI_API_KEY")
        return {
            "markdown": MarkdownTranslationBot(api_key, "PTBR", self._log),
            "html": HTMLTranslationBot(api_key, "PTBR", self._log_lock),
            "xml": XMLTranslationBot(api_key, "PTBR", self._log_lock),
            "text": TextTranslationBot(api_key, "PTBR", self._log_lock),
            "image_factory": lambda workspace: ImageProcessorBot(
                "PTBR", str(workspace), self._log_lock, api_key=api_key
            ),
            "variables": VariableAnalysisBot(api_key, "PTBR", self._log),
            "scriptures": ScriptureCheckBot("PTBR", str(self.hub_dir), self._log_lock),
        }

    @staticmethod
    def _has_translatable_text(content, extension):
        extension = extension.lower()
        if extension in {".html", ".htm"}:
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup.find_all(["script", "style", "code", "pre", "noscript"]):
                tag.decompose()
            text = soup.get_text(" ", strip=True)
        elif extension == ".xml":
            soup = BeautifulSoup(content, "xml")
            text = " ".join(
                tag.get_text(" ", strip=True)
                for tag in soup.find_all(["title", "mattext", "description", "long_description", "fieldentry", "text"])
            )
        elif extension in {".md", ".markdown", ".mdx"}:
            protected, _ = MarkdownTranslationBot._protect(content)
            text = re.sub(r"@@GITHUB_PROTECTED_\d+@@", "", protected)
        else:
            text = content
        return len(re.findall(r"[A-Za-z]{2,}", text)) >= 2

    def _translate_one(self, item, source_root, translated_root, glossary, bots):
        source_path = source_root / item.relative_path
        target_path = translated_root / item.relative_path
        original = source_path.read_text(encoding="utf-8", errors="strict")
        page_title = self.scanner.extract_page_title(original, item.extension, source_path.stem)
        if not self._has_translatable_text(original, item.extension):
            self._log(f"[GitHub] Preserved {item.relative_path}: no translatable prose.")
            return page_title, original, original

        glossary_entries = glossary.relevant_entries(original)
        glossary_mapping = glossary.relevant_mapping(original)
        scriptures = bots["scriptures"].get_scriptures_for_text(original)
        if item.extension in {".md", ".markdown", ".mdx"}:
            translated = bots["markdown"].translate(original, glossary_entries, page_title)
        elif item.extension in {".html", ".htm"}:
            translated = bots["html"].translate_html_content_in_chunks(
                original, glossary_mapping, scriptures, page_title
            )
            soup = BeautifulSoup(translated, "html.parser")
            image_bot = bots.get("image_factory", lambda _workspace: None)(source_path.parent)
            if image_bot:
                for image in soup.find_all("img"):
                    image_bot.process_image_tag(image, page_title)
                translated = str(soup)
        elif item.extension == ".xml":
            translated = bots["xml"].translate_xml_content(
                original, glossary_mapping, scriptures, page_title
            )
        else:
            translated = bots["text"].translate_txt_content(
                original, glossary_mapping, scriptures
            )

        if translated == original:
            raise RuntimeError("Translation returned the source content unchanged.")
        errors = self.validator.validate(original, translated, item.extension)
        if errors:
            raise RuntimeError(" ".join(errors))
        target_path.write_text(translated, encoding="utf-8", newline="")
        self._log(f"[GitHub] Translated {item.relative_path}.")
        return page_title, original, translated

    @staticmethod
    def _blob_url(owner, repository, reference, relative_path):
        return (
            f"https://github.com/{owner}/{repository}/blob/{quote(reference, safe='')}/"
            f"{quote(relative_path, safe='/')}"
        )

    @staticmethod
    def _local_asset_exists(asset, repository_root):
        root = Path(repository_root).resolve()
        parsed_path = unquote(urlparse(asset.asset_path).path)
        if parsed_path.startswith("/"):
            candidate = root / parsed_path.lstrip("/")
        else:
            candidate = root / Path(asset.source_file).parent / parsed_path
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            return False
        return candidate.is_file()

    def _asset_rows(
        self, source_assets, translated_assets, destination_owner, destination_name, source_root
    ):
        translated_lookup = {
            (asset.source_file, asset.asset_path): asset for asset in translated_assets
        }
        rows = []
        issues = {}
        for asset in source_assets:
            translated = translated_lookup.get((asset.source_file, asset.asset_path))
            notes = "External asset; verify the localized destination." if asset.external else ""
            if not asset.external and not self._local_asset_exists(asset, source_root):
                missing_note = f"Referenced local {asset.asset_type.lower()} does not exist."
                notes = (notes + " " + missing_note).strip()
                issues.setdefault(asset.source_file, []).append(
                    f"Missing asset: {asset.asset_path}"
                )
            if translated is None:
                notes = (notes + " Translated reference was not found.").strip()
            rows.append({
                "asset_path": asset.asset_path,
                "tl_link": self._blob_url(
                    destination_owner, destination_name, "main", asset.source_file
                ),
                "notes": notes,
                "alt_text_en": asset.alt_text,
                "alt_text_pt": translated.alt_text if translated else "",
            })
        return rows, issues

    def run(self, repository_url, branch=None):
        source_owner, source_repository = self.repository_manager.parse_repository_url(repository_url)
        authenticated = self.repository_manager.authenticated_user()
        destination_owner = str(authenticated["login"])
        if destination_owner.casefold() == source_owner.casefold():
            raise GitHubTranslationRunError(
                "The source owner and personal destination owner must be different; no repository was created."
            )
        base_name = self.repository_manager.destination_base_name(source_repository, "PTBR", testing=True)
        destination_name = self.repository_manager.choose_destination_name(destination_owner, base_name)
        workspace = self._create_workspace(source_owner, source_repository)
        source_root = workspace / "source"
        translated_root = workspace / "translated"
        report_path = ""

        self._log(
            f"[GitHub] Source {source_owner}/{source_repository} is read-only. "
            f"Planned destination: {destination_owner}/{destination_name}."
        )
        source_metadata = self.repository_manager.clone_source(repository_url, source_root, branch)
        manifest = self.scanner.scan(source_root)
        self.repository_manager.prepare_translation_tree(source_root, translated_root)
        glossary_path = SoftwareDevelopmentGlossary.default_path(self.hub_dir)
        glossary = SoftwareDevelopmentGlossary.load(glossary_path, "PTBR")
        bots = self._bots()

        translated_items = [item for item in manifest if item.action == "translate"]
        successes = {}
        failures = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._translate_one, item, source_root, translated_root, glossary, bots
                ): item
                for item in translated_items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    successes[item.relative_path] = future.result()
                except Exception as error:
                    failures[item.relative_path] = str(error)
                    self._log(f"[GitHub] Concurrent translation failed for {item.relative_path}: {error}")

        # A sequential retry reduces pressure on Gemini and is the final gate.
        for relative_path in list(failures):
            item = next(item for item in translated_items if item.relative_path == relative_path)
            try:
                successes[relative_path] = self._translate_one(
                    item, source_root, translated_root, glossary, bots
                )
                del failures[relative_path]
            except Exception as error:
                failures[relative_path] = str(error)
                self._log(f"[GitHub] Final translation failure for {relative_path}: {error}")

        variable_rows = []
        variable_mapping = {}
        for item in translated_items:
            if item.relative_path in failures:
                continue
            page_title, original, _ = successes[item.relative_path]
            try:
                rows = bots["variables"].analyze(
                    original,
                    item.extension,
                    page_title,
                    item.relative_path,
                    variable_mapping,
                )
                variable_rows.extend(rows)
                for row in rows:
                    variable_mapping.setdefault(row["variable_en"], row["variable_pt"])
            except Exception as error:
                failures[item.relative_path] = f"Variable analysis failed: {error}"
                self._log(f"[GitHub] Variable analysis failed for {item.relative_path}: {error}")

        tree_errors = self.validator.validate_tree(source_root, translated_root, manifest)
        for error in tree_errors:
            failures.setdefault("Repository validation", error)

        source_assets = self.scanner.inventory_assets(source_root, manifest)
        translated_assets = self.scanner.inventory_assets(translated_root)
        asset_rows, asset_issues = self._asset_rows(
            source_assets,
            translated_assets,
            destination_owner,
            destination_name,
            source_root,
        )
        for source_file, issues in asset_issues.items():
            detail = "; ".join(issues)
            failures[source_file] = (
                f"{failures[source_file]} {detail}" if source_file in failures else detail
            )

        source_reference = source_metadata.get("commit_sha") or source_metadata.get("branch", "main")
        review_rows = []
        for item in translated_items:
            page_title = successes.get(item.relative_path, (Path(item.relative_path).stem,))[0]
            review_rows.append({
                "page_name": page_title,
                "type": item.content_type,
                "link_en": self._blob_url(source_owner, source_repository, source_reference, item.relative_path),
                "link_pt": self._blob_url(destination_owner, destination_name, "main", item.relative_path),
                "status": "Failed" if item.relative_path in failures else "Translated",
                "notes": failures.get(item.relative_path, ""),
            })
        if "Repository validation" in failures:
            review_rows.append({
                "page_name": "Repository validation",
                "type": "Validation",
                "status": "Failed",
                "notes": failures["Repository validation"],
            })

        report_path = self.report_generator.generate(
            destination_name, review_rows, variable_rows, asset_rows
        )
        self._log(f"[GitHub] Report generated: {report_path}")

        if failures:
            raise GitHubTranslationRunError(
                f"{len(failures)} file or validation failure(s) remain. No repository was created.",
                report_path,
                str(workspace),
            )

        published = self.repository_manager.publish_translation(
            translated_root, destination_owner, destination_name, source_metadata
        )
        return GitHubTranslationResult(
            repository_url=published["repository_url"],
            pages_url=published["pages_url"],
            report_path=report_path,
            workspace_path=str(workspace),
            repository_name=destination_name,
        )
