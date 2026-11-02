"""Safe, UI-facing updater for Translation HUB installations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence


class HubUpdateError(RuntimeError):
    """Raised when the HUB cannot be safely fast-forwarded from Git."""


@dataclass(frozen=True)
class HubUpdateResult:
    updated: bool
    previous_revision: str
    current_revision: str


class HubUpdater:
    """Fast-forward one installation from a configured public Git branch."""

    def __init__(
        self,
        repository_dir: str | os.PathLike[str],
        *,
        remote: str = "origin",
        branch: str = "main",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.repository_dir = Path(repository_dir).resolve()
        self.remote = remote
        self.branch = branch
        self._runner = runner

    def _git(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = ["git", *arguments]
        try:
            result = self._runner(
                command,
                cwd=str(self.repository_dir),
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as error:
            raise HubUpdateError(
                "Git is not installed or is not available on this computer's PATH."
            ) from error
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "Unknown Git error").strip()
            raise HubUpdateError(detail)
        return result

    def update(self, status_callback: Callable[[str], None] | None = None) -> HubUpdateResult:
        """Fetch and fast-forward from the configured branch without overwriting edits."""

        report = status_callback or (lambda _message: None)
        if not (self.repository_dir / ".git").exists():
            raise HubUpdateError(
                f"Translation HUB is not a Git checkout: {self.repository_dir}"
            )

        current_branch = self._git("branch", "--show-current").stdout.strip()
        if current_branch != self.branch:
            raise HubUpdateError(
                f"Translation HUB must be on the {self.branch!r} branch before updating; "
                f"the current branch is {current_branch or 'detached HEAD'!r}."
            )

        tracked_status = self._git(
            "status",
            "--porcelain",
            "--untracked-files=no",
        ).stdout.rstrip()
        if tracked_status.strip():
            changed_paths = "\n".join(
                line[3:] if len(line) > 3 else line
                for line in tracked_status.splitlines()
            )
            raise HubUpdateError(
                "The update was stopped because tracked files have local changes. "
                "No files were overwritten. Ask the HUB administrator to review:\n"
                f"{changed_paths}"
            )

        previous_revision = self._git("rev-parse", "HEAD").stdout.strip()
        report(f"Checking {self.remote}/{self.branch} for updates...")
        self._git("fetch", self.remote, self.branch)
        upstream_revision = self._git("rev-parse", "FETCH_HEAD").stdout.strip()

        if previous_revision == upstream_revision:
            report("Translation HUB is already up to date.")
            return HubUpdateResult(
                updated=False,
                previous_revision=previous_revision,
                current_revision=previous_revision,
            )

        ancestry = self._git(
            "merge-base",
            "--is-ancestor",
            previous_revision,
            upstream_revision,
            check=False,
        )
        if ancestry.returncode != 0:
            raise HubUpdateError(
                "The local installation and origin/main have diverged. The updater will "
                "not overwrite either history; ask the HUB administrator to repair this "
                "installation."
            )

        report("Downloading and installing the newest Translation HUB version...")
        self._git("pull", "--ff-only", self.remote, self.branch)
        current_revision = self._git("rev-parse", "HEAD").stdout.strip()
        if current_revision != upstream_revision:
            raise HubUpdateError(
                "Git completed without installing the expected origin/main revision."
            )

        report("Translation HUB updated successfully. Restarting...")
        return HubUpdateResult(
            updated=True,
            previous_revision=previous_revision,
            current_revision=current_revision,
        )


def build_restart_command(
    entry_script: str | os.PathLike[str],
    arguments: Sequence[str] | None = None,
) -> list[str]:
    """Return the command used to replace the current HUB process."""

    extra_arguments = list(arguments or ())
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_arguments]
    return [sys.executable, str(Path(entry_script).resolve()), *extra_arguments]


def restart_hub(
    entry_script: str | os.PathLike[str],
    arguments: Sequence[str] | None = None,
) -> None:
    """Replace the running process with the freshly updated HUB."""

    command = build_restart_command(entry_script, arguments)
    os.execv(command[0], command)
