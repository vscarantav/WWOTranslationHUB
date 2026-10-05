import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse


class GitHubRepositoryError(RuntimeError):
    pass


class GitHubRepositoryManager:
    """Clone a source read-only and publish only to a new personal repository."""

    API_ROOT = "https://api.github.com"
    PROTECTED_SOURCE_OWNERS = {"byui-cse"}

    def __init__(self, token: str, log_func=print, api_request=None, git_runner=None):
        self.token = (token or "").strip()
        if not self.token:
            raise ValueError("A GitHub personal access token is required.")
        self.log = log_func
        self._api_request_override = api_request
        self._git_runner_override = git_runner

    @staticmethod
    def parse_repository_url(repository_url: str) -> tuple[str, str]:
        raw_url = (repository_url or "").strip().rstrip("/")
        parsed = urlparse(raw_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise ValueError(
                "Enter an HTTPS GitHub repository or GitHub Pages URL."
            )
        parts = [part for part in parsed.path.split("/") if part]
        if hostname == "github.com":
            if len(parts) != 2:
                raise ValueError("The GitHub URL must identify exactly one owner and repository.")
            owner = parts[0]
            repository = re.sub(r"\.git$", "", parts[1], flags=re.IGNORECASE)
        elif hostname.endswith(".github.io") and hostname != "github.io":
            owner = hostname[:-len(".github.io")]
            if not parts:
                raise ValueError(
                    "The GitHub Pages URL must include the project repository name."
                )
            repository = parts[0]
        else:
            raise ValueError(
                "Enter an HTTPS GitHub repository URL or a standard owner.github.io project URL."
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository):
            raise ValueError("The GitHub owner or repository name contains unsupported characters.")
        return owner, repository

    @classmethod
    def canonical_repository_url(cls, repository_url: str) -> str:
        owner, repository = cls.parse_repository_url(repository_url)
        return f"https://github.com/{owner}/{repository}.git"

    @staticmethod
    def destination_base_name(source_repository: str, language="PTBR", testing=True) -> str:
        language = language.upper()
        suffix = "pt" if language == "PTBR" else "spa"
        if testing:
            if re.search(r"-v2$", source_repository, flags=re.IGNORECASE):
                return re.sub(
                    r"-v2$",
                    f"-test1-{suffix}",
                    source_repository,
                    flags=re.IGNORECASE,
                )
            return f"{source_repository}-test1-{suffix}"
        if re.search(r"-v2$", source_repository, flags=re.IGNORECASE):
            return re.sub(r"-v2$", f"-{suffix}", source_repository, flags=re.IGNORECASE)
        return f"{source_repository}-{suffix}"

    def _api_request(self, method: str, path: str, payload=None):
        if self._api_request_override:
            return self._api_request_override(method, path, payload)

        url = f"{self.API_ROOT}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "WWO-Translation-Hub",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            message = body
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                pass
            exception = GitHubRepositoryError(
                f"GitHub API {method} {path} failed ({error.code}): {message}"
            )
            exception.status_code = error.code
            raise exception from error
        except urllib.error.URLError as error:
            raise GitHubRepositoryError(f"Could not reach GitHub API: {error.reason}") from error

    def authenticated_user(self) -> dict:
        user = self._api_request("GET", "/user")
        login = str(user.get("login", "")).strip()
        if not login:
            raise GitHubRepositoryError("The GitHub token did not return an authenticated user.")
        return user

    def repository_exists(self, owner: str, repository: str) -> bool:
        try:
            self._api_request(
                "GET",
                f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}",
            )
            return True
        except GitHubRepositoryError as error:
            if getattr(error, "status_code", None) == 404:
                return False
            raise

    def choose_destination_name(self, owner: str, base_name: str) -> str:
        if owner.casefold() in {item.casefold() for item in self.PROTECTED_SOURCE_OWNERS}:
            raise GitHubRepositoryError("CSE organizations cannot be translation destinations.")
        candidate = base_name
        number = 2
        while self.repository_exists(owner, candidate):
            candidate = f"{base_name}-{number}"
            number += 1
        return candidate

    @staticmethod
    def _write_askpass_script(directory: Path) -> Path:
        if os.name == "nt":
            script = directory / "github-askpass.bat"
            script.write_text(
                "@echo off\r\n"
                "echo %1 | findstr /I \"Username\" >nul\r\n"
                "if %errorlevel%==0 (echo x-access-token) else (echo %GITHUB_TRANSLATION_TOKEN%)\r\n",
                encoding="utf-8",
            )
        else:
            script = directory / "github-askpass.sh"
            script.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in *Username*) echo x-access-token ;; *) printf '%s\\n' \"$GITHUB_TRANSLATION_TOKEN\" ;; esac\n",
                encoding="utf-8",
            )
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    def _run_git(self, arguments, cwd=None, authenticate=False):
        command = ["git", *arguments]
        if self._git_runner_override:
            return self._git_runner_override(command, cwd, authenticate)

        environment = os.environ.copy()
        temporary = None
        if authenticate:
            temporary = tempfile.TemporaryDirectory(prefix="translation-hub-askpass-")
            askpass = self._write_askpass_script(Path(temporary.name))
            environment.update({
                "GIT_ASKPASS": str(askpass),
                "GIT_TERMINAL_PROMPT": "0",
                "GITHUB_TRANSLATION_TOKEN": self.token,
            })
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            if temporary:
                temporary.cleanup()
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Git command failed.").strip()
            detail = detail.replace(self.token, "***")
            raise GitHubRepositoryError(f"git {arguments[0]} failed: {detail}")
        return completed.stdout.strip()

    def clone_source(self, repository_url: str, destination, branch=None) -> dict:
        owner, repository = self.parse_repository_url(repository_url)
        clone_url = self.canonical_repository_url(repository_url)
        destination_path = Path(destination).resolve()
        if destination_path.exists() and any(destination_path.iterdir()):
            raise GitHubRepositoryError(f"Clone destination is not empty: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        arguments = ["clone", "--origin", "upstream"]
        if branch:
            arguments.extend(["--branch", branch])
        arguments.extend([clone_url, str(destination_path)])
        self.log(f"[GitHub] Cloning read-only source {owner}/{repository}...")
        self._run_git(arguments, authenticate=True)

        # Defense in depth: a later accidental `git push upstream` must fail.
        self._run_git(
            ["remote", "set-url", "--push", "upstream", "disabled-source-push://read-only"],
            cwd=destination_path,
        )
        resolved_branch = self._run_git(["branch", "--show-current"], cwd=destination_path) or branch or "main"
        commit_sha = self._run_git(["rev-parse", "HEAD"], cwd=destination_path)
        return {
            "owner": owner,
            "repository": repository,
            "branch": resolved_branch,
            "commit_sha": commit_sha,
            "path": str(destination_path),
        }

    @staticmethod
    def prepare_translation_tree(source_dir, destination_dir):
        source = Path(source_dir).resolve()
        destination = Path(destination_dir).resolve()
        if not source.is_dir():
            raise GitHubRepositoryError(f"Source clone does not exist: {source}")
        if destination.exists():
            raise GitHubRepositoryError(f"Translated destination already exists: {destination}")

        def ignore(directory, names):
            ignored = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}
            relative = Path(directory).resolve().relative_to(source)
            if relative.as_posix() == ".github":
                ignored.add("workflows")
            return [name for name in names if name in ignored]

        shutil.copytree(source, destination, ignore=ignore)
        if (destination / ".git").exists():
            raise GitHubRepositoryError("Translated output unexpectedly contains source Git metadata.")
        return destination

    def create_personal_repository(self, owner: str, repository: str) -> dict:
        authenticated = self.authenticated_user().get("login", "")
        if owner.casefold() != str(authenticated).casefold():
            raise GitHubRepositoryError("Destination owner must be the authenticated personal account.")
        if owner.casefold() in {item.casefold() for item in self.PROTECTED_SOURCE_OWNERS}:
            raise GitHubRepositoryError("CSE organizations cannot be translation destinations.")
        return self._api_request("POST", "/user/repos", {
            "name": repository,
            "private": False,
            "auto_init": False,
            "description": "Portuguese textbook translation generated by WWO Translation Hub",
        })

    def publish_translation(self, translated_dir, owner: str, repository: str, source_metadata: dict) -> dict:
        authenticated = self.authenticated_user()
        login = str(authenticated.get("login", ""))
        if login.casefold() != owner.casefold():
            raise GitHubRepositoryError("Destination owner changed before publication.")
        if owner.casefold() in {item.casefold() for item in self.PROTECTED_SOURCE_OWNERS}:
            raise GitHubRepositoryError("Refusing to publish into a protected CSE organization.")

        created = self.create_personal_repository(owner, repository)
        translated = Path(translated_dir).resolve()
        if (translated / ".git").exists():
            raise GitHubRepositoryError("Translated directory already contains Git metadata.")

        remote_url = f"https://github.com/{owner}/{repository}.git"
        self._run_git(["init", "-b", "main"], cwd=translated)
        self._run_git(["config", "user.name", login], cwd=translated)
        email = authenticated.get("email") or f"{login}@users.noreply.github.com"
        self._run_git(["config", "user.email", email], cwd=translated)
        self._run_git(["remote", "add", "origin", remote_url], cwd=translated)
        self._run_git(["add", "-A"], cwd=translated)
        source_reference = (
            f"{source_metadata.get('owner', '')}/{source_metadata.get('repository', '')}"
            f"@{source_metadata.get('commit_sha', '')[:12]}"
        )
        self._run_git(
            ["commit", "-m", f"Add Portuguese translation of {source_reference}"],
            cwd=translated,
        )
        self._run_git(["push", "-u", "origin", "main"], cwd=translated, authenticate=True)

        self._api_request("POST", f"/repos/{quote(owner)}/{quote(repository)}/pages", {
            "source": {"branch": "main", "path": "/"},
        })
        return {
            "repository_url": created.get("html_url") or f"https://github.com/{owner}/{repository}",
            "pages_url": f"https://{owner}.github.io/{repository}/",
            "repository": repository,
            "owner": owner,
            "branch": "main",
        }
