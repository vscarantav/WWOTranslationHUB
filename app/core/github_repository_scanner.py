import mimetypes
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup


TRANSLATABLE_EXTENSIONS = {".html", ".htm", ".md", ".markdown", ".mdx", ".xml", ".txt"}
IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
DOWNLOAD_EXTENSIONS = {
    ".csv", ".doc", ".docx", ".epub", ".odp", ".ods", ".odt",
    ".pdf", ".ppt", ".pptx", ".rtf", ".xls", ".xlsx", ".zip",
}
IGNORED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__",
    "node_modules", ".pytest_cache", ".mypy_cache", ".next", ".nuxt",
}


@dataclass(frozen=True)
class RepositoryFile:
    relative_path: str
    extension: str
    action: str
    content_type: str
    size: int

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AssetReference:
    source_file: str
    page_title: str
    asset_path: str
    asset_type: str
    alt_text: str = ""
    external: bool = False

    def to_dict(self):
        return asdict(self)


class GitHubRepositoryScanner:
    """Inventory translatable content and referenced assets in a repository."""

    def __init__(self, ignored_directories=None):
        self.ignored_directories = set(ignored_directories or IGNORED_DIRECTORIES)

    @staticmethod
    def _content_type(extension: str) -> str:
        return {
            ".html": "HTML",
            ".htm": "HTML",
            ".md": "Markdown",
            ".markdown": "Markdown",
            ".mdx": "MDX",
            ".xml": "XML",
            ".txt": "Text",
        }.get(extension, "Asset")

    def scan(self, root_dir) -> list[RepositoryFile]:
        root = Path(root_dir).resolve()
        if not root.is_dir():
            raise ValueError(f"Repository directory does not exist: {root}")

        files = []
        for current_root, directories, filenames in os.walk(root):
            directories[:] = sorted(
                directory
                for directory in directories
                if directory not in self.ignored_directories
            )
            current = Path(current_root)
            for filename in sorted(filenames):
                path = current / filename
                relative = path.relative_to(root).as_posix()

                # Workflows copied into a newly created personal repository could
                # execute with different secrets and permissions. They are never
                # carried into the translated output automatically.
                if relative.startswith(".github/workflows/"):
                    action = "ignored"
                else:
                    extension = path.suffix.lower()
                    action = "translate" if extension in TRANSLATABLE_EXTENSIONS else "copy"
                extension = path.suffix.lower()
                files.append(RepositoryFile(
                    relative_path=relative,
                    extension=extension,
                    action=action,
                    content_type=self._content_type(extension),
                    size=path.stat().st_size,
                ))
        return files

    @staticmethod
    def extract_page_title(content: str, extension: str, fallback: str) -> str:
        extension = extension.lower()
        if extension in {".html", ".htm"}:
            soup = BeautifulSoup(content, "html.parser")
            title = soup.find("title") or soup.find(["h1", "h2"])
            if title and title.get_text(" ", strip=True):
                return title.get_text(" ", strip=True)
        elif extension in {".md", ".markdown", ".mdx"}:
            match = re.search(r"(?m)^#\s+(.+?)\s*$", content)
            if match:
                return re.sub(r"[`*_]", "", match.group(1)).strip()
        elif extension == ".xml":
            soup = BeautifulSoup(content, "xml")
            title = soup.find("title")
            if title and title.get_text(" ", strip=True):
                return title.get_text(" ", strip=True)
        return fallback

    @staticmethod
    def _asset_kind(asset_path: str) -> str | None:
        parsed = urlparse(asset_path)
        extension = Path(unquote(parsed.path)).suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            return "Image"
        if extension in DOWNLOAD_EXTENSIONS:
            return "File"
        mime_type, _ = mimetypes.guess_type(parsed.path)
        if mime_type and mime_type.startswith("image/"):
            return "Image"
        return None

    @classmethod
    def _reference(cls, source_file, page_title, asset_path, alt_text=""):
        asset_path = (asset_path or "").strip()
        kind = cls._asset_kind(asset_path)
        if not asset_path or not kind:
            return None
        parsed = urlparse(asset_path)
        return AssetReference(
            source_file=source_file,
            page_title=page_title,
            asset_path=asset_path,
            asset_type=kind,
            alt_text=(alt_text or "").strip(),
            external=parsed.scheme in {"http", "https"},
        )

    def extract_assets(self, filepath, repository_root) -> list[AssetReference]:
        path = Path(filepath)
        root = Path(repository_root).resolve()
        relative_path = path.resolve().relative_to(root).as_posix()
        extension = path.suffix.lower()
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        page_title = self.extract_page_title(content, extension, path.stem)
        references = []

        if extension in {".html", ".htm", ".xml"}:
            soup = BeautifulSoup(content, "xml" if extension == ".xml" else "html.parser")
            for image in soup.find_all("img"):
                reference = self._reference(
                    relative_path,
                    page_title,
                    image.get("src", ""),
                    image.get("alt", ""),
                )
                if reference:
                    references.append(reference)
            for link in soup.find_all("a", href=True):
                reference = self._reference(
                    relative_path,
                    page_title,
                    link.get("href", ""),
                    "",
                )
                if reference and reference.asset_type == "File":
                    references.append(reference)

        if extension in {".md", ".markdown", ".mdx"}:
            for match in re.finditer(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)", content):
                reference = self._reference(
                    relative_path,
                    page_title,
                    match.group(2),
                    match.group(1),
                )
                if reference:
                    references.append(reference)
            for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)", content):
                reference = self._reference(relative_path, page_title, match.group(1), "")
                if reference and reference.asset_type == "File":
                    references.append(reference)

        seen = set()
        unique = []
        for reference in references:
            key = (reference.source_file, reference.asset_path, reference.asset_type)
            if key not in seen:
                seen.add(key)
                unique.append(reference)
        return unique

    def inventory_assets(self, root_dir, manifest=None) -> list[AssetReference]:
        root = Path(root_dir).resolve()
        manifest = manifest if manifest is not None else self.scan(root)
        references = []
        for item in manifest:
            if item.action != "translate":
                continue
            references.extend(self.extract_assets(root / item.relative_path, root))
        return references
