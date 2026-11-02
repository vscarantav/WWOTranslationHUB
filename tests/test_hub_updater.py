import subprocess
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.hub_updater import (
    HubUpdateError,
    HubUpdater,
    build_restart_command,
)


class FakeGitRunner:
    def __init__(self, *, dirty="", fetched_revision="old", diverged=False):
        self.dirty = dirty
        self.fetched_revision = fetched_revision
        self.diverged = diverged
        self.updated = False
        self.commands = []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        arguments = command[1:]
        stdout = ""
        stderr = ""
        returncode = 0

        if arguments == ["branch", "--show-current"]:
            stdout = "main\n"
        elif arguments == ["status", "--porcelain", "--untracked-files=no"]:
            stdout = self.dirty
        elif arguments == ["rev-parse", "HEAD"]:
            stdout = f"{'new' if self.updated else 'old'}\n"
        elif arguments == ["fetch", "origin", "main"]:
            pass
        elif arguments == ["rev-parse", "FETCH_HEAD"]:
            stdout = f"{self.fetched_revision}\n"
        elif arguments[:2] == ["merge-base", "--is-ancestor"]:
            returncode = 1 if self.diverged else 0
        elif arguments == ["pull", "--ff-only", "origin", "main"]:
            self.updated = True
        else:
            returncode = 2
            stderr = f"Unexpected command: {arguments}"

        return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class HubUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.repository = Path.cwd() / "tests" / f"_hub_updater_{uuid.uuid4().hex}"
        self.repository.mkdir(parents=True)
        (self.repository / ".git").mkdir()

    def tearDown(self):
        shutil.rmtree(self.repository, ignore_errors=True)

    def test_reports_when_main_is_already_current_without_pulling(self):
        runner = FakeGitRunner(fetched_revision="old")
        messages = []

        result = HubUpdater(self.repository, runner=runner).update(messages.append)

        self.assertFalse(result.updated)
        self.assertEqual(result.previous_revision, "old")
        self.assertEqual(result.current_revision, "old")
        self.assertNotIn(
            ["git", "pull", "--ff-only", "origin", "main"],
            runner.commands,
        )
        self.assertEqual(messages[-1], "Translation HUB is already up to date.")

    def test_fast_forwards_origin_main_and_reports_restart_status(self):
        runner = FakeGitRunner(fetched_revision="new")
        messages = []

        result = HubUpdater(self.repository, runner=runner).update(messages.append)

        self.assertTrue(result.updated)
        self.assertEqual(result.previous_revision, "old")
        self.assertEqual(result.current_revision, "new")
        self.assertIn(
            ["git", "pull", "--ff-only", "origin", "main"],
            runner.commands,
        )
        self.assertEqual(
            messages[-1],
            "Translation HUB updated successfully. Restarting...",
        )

    def test_refuses_to_overwrite_tracked_local_changes(self):
        runner = FakeGitRunner(dirty=" M app/main_ui.py\n")

        with self.assertRaisesRegex(HubUpdateError, "app/main_ui.py"):
            HubUpdater(self.repository, runner=runner).update()

        self.assertNotIn(["git", "fetch", "origin", "main"], runner.commands)

    def test_refuses_diverged_history_without_pulling(self):
        runner = FakeGitRunner(fetched_revision="new", diverged=True)

        with self.assertRaisesRegex(HubUpdateError, "diverged"):
            HubUpdater(self.repository, runner=runner).update()

        self.assertNotIn(
            ["git", "pull", "--ff-only", "origin", "main"],
            runner.commands,
        )

    def test_requires_a_git_checkout(self):
        non_repository = self.repository / "not-a-repository"
        non_repository.mkdir()
        try:
            with self.assertRaisesRegex(HubUpdateError, "not a Git checkout"):
                HubUpdater(non_repository, runner=FakeGitRunner()).update()
        finally:
            shutil.rmtree(non_repository, ignore_errors=True)

    def test_restart_command_relaunches_main_ui_with_current_python(self):
        entry_script = self.repository / "app" / "main_ui.py"

        with patch("core.hub_updater.sys.frozen", False, create=True):
            command = build_restart_command(entry_script)

        self.assertEqual(command, [sys.executable, str(entry_script.resolve())])


if __name__ == "__main__":
    unittest.main()
