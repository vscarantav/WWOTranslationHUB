"""Credential-safe Classic Canvas Question Bank Translation ID renaming."""

from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from core.canvas_translation_id_reconciler import (
    APPROVAL_PHRASE,
    CanvasTranslationIdError,
    parse_canvas_course_url,
)
from core.translation_id_registry import (
    LANGUAGES,
    VISIBLE_MARKER_RE,
    TranslationIdRegistry,
    TranslationIdRegistryError,
)


class CanvasQuestionBankError(RuntimeError):
    """Raised when Question Bank discovery or renaming is unsafe."""


def format_question_bank_name(name: str, translation_id: str) -> str:
    name = str(name or "").strip()
    markers = {marker.upper() for marker in VISIBLE_MARKER_RE.findall(name)}
    if markers == {translation_id}:
        return name
    if markers:
        raise CanvasQuestionBankError(
            f"Question Bank already contains a different Translation ID: {', '.join(sorted(markers))}."
        )
    if not name:
        raise CanvasQuestionBankError("Question Bank name is empty.")
    return f"{name} TranslationID: {translation_id}"


class CanvasQuestionBankRenamer:
    """Plan and perform exact, verified Classic Question Bank renames."""

    def __init__(
        self,
        registry: TranslationIdRegistry | Mapping[str, Any] | os.PathLike[str] | str,
        course_url: str,
        language: str,
        mode: str,
        profile_dir: Optional[os.PathLike[str] | str] = None,
        rollback_root: Optional[os.PathLike[str] | str] = None,
        playwright_factory=None,
    ) -> None:
        self.registry = self._coerce_registry(registry)
        self.course = parse_canvas_course_url(course_url)
        self.language = str(language).upper()
        if self.language not in LANGUAGES:
            raise CanvasQuestionBankError(f"Unsupported registry language: {language}")
        if mode not in {"source-register", "target-reconcile"}:
            raise CanvasQuestionBankError(f"Unsupported Question Bank mode: {mode}")
        if mode == "source-register" and self.language != "EN":
            raise CanvasQuestionBankError("Source Question Bank registration must use EN.")
        if mode == "target-reconcile" and self.language == "EN":
            raise CanvasQuestionBankError("Target Question Bank reconciliation requires a target language.")
        if (
            mode == "source-register"
            and self.registry.source_course_id
            and self.registry.source_course_id != self.course["course_id"]
        ):
            raise CanvasQuestionBankError(
                "The selected source course does not match the registry source course ID."
            )
        self.mode = mode
        local_app_data = os.getenv("LOCALAPPDATA")
        if not profile_dir and not local_app_data:
            raise CanvasQuestionBankError(
                "LOCALAPPDATA is required for the dedicated Canvas browser profile."
            )
        self.profile_dir = Path(
            profile_dir
            or Path(local_app_data) / "WWOTranslationHUB" / "playwright" / "canvas-profile"
        ).resolve()
        self.rollback_root = Path(
            rollback_root or Path.cwd() / "Translation ID Rollbacks"
        ).resolve()
        self.playwright_factory = playwright_factory

    def plan(self, live_banks: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        """Match exact normalized names and classify every expected/live bank."""
        live_banks = [deepcopy(dict(bank)) for bank in live_banks]
        expected = [
            item
            for item in self.registry.items
            if item.get("item_type") == "Question Bank" and not item.get("retired")
        ]
        changes = []
        matched_live_indexes = set()
        for item in expected:
            expected_names = {
                self._normalize_name(item.get("source_title", "")),
                self._normalize_name(item.get("instances", {}).get("EN", {}).get("title", "")),
                self._normalize_name(item.get("instances", {}).get(self.language, {}).get("title", "")),
            }
            expected_names.discard("")
            matches = [
                (index, bank)
                for index, bank in enumerate(live_banks)
                if self._normalize_name(bank.get("name", "")) in expected_names
            ]
            if len(matches) != 1:
                changes.append({
                    "translation_id": item["translation_id"],
                    "source_title": item["source_title"],
                    "status": "Missing" if not matches else "Duplicate",
                    "detail": (
                        "No exact normalized-name match was found."
                        if not matches
                        else f"{len(matches)} exact normalized-name matches were found."
                    ),
                    "live_id": None,
                    "old_name": None,
                    "new_name": None,
                    "url": None,
                    "editable": False,
                })
                continue
            index, bank = matches[0]
            matched_live_indexes.add(index)
            old_name = str(bank.get("name", "")).strip()
            editable = bool(bank.get("editable", True))
            try:
                new_name = format_question_bank_name(old_name, item["translation_id"])
                markers = {value.upper() for value in VISIBLE_MARKER_RE.findall(old_name)}
                if markers == {item["translation_id"]}:
                    status = "Correct"
                    detail = ""
                elif markers:
                    status = "Conflict"
                    detail = "A different Translation ID is already present."
                elif not editable:
                    status = "Non-editable"
                    detail = "Canvas does not present a supported edit control for this bank."
                else:
                    status = "Rename"
                    detail = ""
            except CanvasQuestionBankError as error:
                status = "Conflict"
                detail = str(error)
                new_name = None
            if old_name.casefold() == "unfiled questions" and not editable:
                status = "Non-editable"
                detail = "Canvas-managed Unfiled Questions bank is not editable."
            self.registry.update_instance(
                item["translation_id"],
                self.language,
                course_id=self.course["course_id"],
                content_id=str(bank.get("id") or ""),
                title=old_name,
                url=bank.get("url"),
                presence="present",
                id_status=status.casefold(),
            )
            changes.append({
                "translation_id": item["translation_id"],
                "source_title": item["source_title"],
                "status": status,
                "detail": detail,
                "live_id": str(bank.get("id") or ""),
                "old_name": old_name,
                "new_name": new_name,
                "url": bank.get("url"),
                "editable": editable,
            })

        extras = [
            {
                "live_id": str(bank.get("id") or ""),
                "name": bank.get("name"),
                "url": bank.get("url"),
                "editable": bool(bank.get("editable", True)),
            }
            for index, bank in enumerate(live_banks)
            if index not in matched_live_indexes
        ]
        summary = {}
        for change in changes:
            summary[change["status"]] = summary.get(change["status"], 0) + 1
        if extras:
            summary["Extra"] = len(extras)
        return {
            "mode": self.mode,
            "language": self.language,
            "course_id": self.course["course_id"],
            "course_url": self.course["course_url"],
            "generated_at": datetime.now().astimezone().isoformat(),
            "summary": summary,
            "changes": changes,
            "extra_banks": extras,
        }

    def discover(self, login_checkpoint) -> List[Dict[str, Any]]:
        """Open a visible persistent browser and enumerate bank links after login."""
        if login_checkpoint is None:
            raise CanvasQuestionBankError(
                "A user-controlled Canvas/SSO login checkpoint is required."
            )
        self._ensure_profile_is_outside_repository()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        with self._playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=False,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                manage_url = self.course["course_url"] + "/question_banks"
                page.goto(manage_url, wait_until="domcontentloaded")
                if login_checkpoint(
                    {
                        "action": "Complete Canvas/SSO login in the visible browser",
                        "url": manage_url,
                        "details": "The HUB does not read or store your password. Continue only after the Question Banks page is visible.",
                    }
                ) is False:
                    raise CanvasQuestionBankError("Canvas login checkpoint was cancelled.")
                page.goto(manage_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                return self._enumerate_page_banks(page)
            finally:
                context.close()

    def apply(self, plan, approval, login_checkpoint) -> Dict[str, Any]:
        """Rename sequentially, stop on first unknown state, and verify each bank."""
        if approval != APPROVAL_PHRASE:
            raise CanvasQuestionBankError(
                f"Question Bank writes require the exact approval phrase: {APPROVAL_PHRASE}"
            )
        self.validate_plan_for_apply(plan)

        self._ensure_profile_is_outside_repository()
        rollback_dir = self._create_rollback_directory()
        self.registry.save(rollback_dir / "registry-before.json")
        self._write_json(rollback_dir / "question-bank-plan.json", plan)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        results = []
        with self._playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=False,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                manage_url = self.course["course_url"] + "/question_banks"
                page.goto(manage_url, wait_until="domcontentloaded")
                if login_checkpoint(
                    {
                        "action": "Confirm Canvas/SSO login",
                        "url": manage_url,
                        "details": "Continue only after the Question Banks page is visible.",
                    }
                ) is False:
                    raise CanvasQuestionBankError("Canvas login checkpoint was cancelled.")
                for change in plan.get("changes", []):
                    if change.get("status") != "Rename":
                        results.append({**deepcopy(change), "write_result": "Skipped"})
                        continue
                    self._rename_one(page, change)
                    screenshot_path = rollback_dir / f"{change['translation_id']}.png"
                    page.screenshot(path=str(screenshot_path), full_page=False)
                    self.registry.update_instance(
                        change["translation_id"],
                        self.language,
                        course_id=self.course["course_id"],
                        content_id=change.get("live_id"),
                        title=change["new_name"],
                        url=change.get("url"),
                        presence="present",
                        id_status="verified",
                    )
                    record = {**deepcopy(change), "write_result": "Verified", "screenshot": str(screenshot_path)}
                    results.append(record)
                    self._write_json(
                        rollback_dir / f"{change['translation_id']}.json",
                        record,
                    )
            finally:
                context.close()
        self.registry.save(rollback_dir / "registry-after.json")
        output = {
            "course_id": self.course["course_id"],
            "mode": self.mode,
            "language": self.language,
            "rollback_directory": str(rollback_dir),
            "results": results,
        }
        self._write_json(rollback_dir / "final-results.json", output)
        return output

    def validate_plan_for_apply(self, plan) -> None:
        """Reject any dry-run state that could cause a partial registration."""
        if str(plan.get("course_id")) != self.course["course_id"]:
            raise CanvasQuestionBankError("Question Bank dry-run course does not match.")
        if plan.get("mode") != self.mode or plan.get("language") != self.language:
            raise CanvasQuestionBankError(
                "Question Bank dry-run mode/language does not match."
            )
        blockers = [
            change
            for change in plan.get("changes", [])
            if change.get("status") in {"Missing", "Duplicate", "Conflict"}
        ]
        if blockers or plan.get("extra_banks"):
            raise CanvasQuestionBankError(
                "Question Bank writes are blocked until missing, duplicate, conflict, and extra-bank results are resolved."
            )

    def clear_local_session(self) -> bool:
        """Clear only the dedicated local Canvas profile."""
        self._ensure_profile_is_outside_repository()
        if not self.profile_dir.exists():
            return False
        import shutil

        shutil.rmtree(self.profile_dir)
        return True

    def _rename_one(self, page, change):
        if not change.get("url"):
            raise CanvasQuestionBankError(
                f"Question Bank {change['translation_id']} has no verified Canvas URL."
            )
        page.goto(change["url"], wait_until="domcontentloaded")
        edit_control = page.get_by_role(
            "button", name=re.compile(r"edit.*(bank|name)|rename", re.IGNORECASE)
        )
        if edit_control.count() != 1:
            edit_control = page.get_by_role(
                "link", name=re.compile(r"edit.*(bank|name)|rename", re.IGNORECASE)
            )
        if edit_control.count() != 1:
            raise CanvasQuestionBankError(
                f"Canvas edit-name control is missing or ambiguous for {change['translation_id']}."
            )
        edit_control.click()
        name_input = page.get_by_role(
            "textbox", name=re.compile(r"bank.*name|name", re.IGNORECASE)
        )
        if name_input.count() != 1:
            raise CanvasQuestionBankError(
                f"Canvas bank-name field is missing or ambiguous for {change['translation_id']}."
            )
        name_input.fill(change["new_name"])
        save_button = page.get_by_role(
            "button", name=re.compile(r"save|update", re.IGNORECASE)
        )
        if save_button.count() != 1:
            raise CanvasQuestionBankError(
                f"Canvas save control is missing or ambiguous for {change['translation_id']}."
            )
        save_button.click()
        page.wait_for_load_state("networkidle")
        page.reload(wait_until="domcontentloaded")
        names = [bank["name"] for bank in self._enumerate_page_banks(page)]
        if change["new_name"] not in names and change["new_name"] not in page.locator("body").inner_text():
            raise CanvasQuestionBankError(
                f"Canvas did not verify the new name for {change['translation_id']}; write run stopped."
            )

    def _enumerate_page_banks(self, page):
        links = page.locator('a[href*="/question_banks/"]')
        banks = []
        seen = set()
        for index in range(links.count()):
            link = links.nth(index)
            name = link.inner_text().strip()
            url = link.get_attribute("href") or ""
            if not name or url in seen:
                continue
            seen.add(url)
            if url.startswith("/"):
                url = self.course["origin"] + url
            bank_id_match = re.search(r"/question_banks/(\d+)", url)
            if not bank_id_match:
                continue
            # Canvas does not consistently expose an edit control on the bank
            # listing page. Normal banks are therefore considered candidates;
            # the edit-page checks still fail closed before any write. Canvas'
            # built-in Unfiled Questions bank is the one known non-editable bank.
            editable = name.casefold() != "unfiled questions"
            banks.append({
                "id": bank_id_match.group(1),
                "name": name,
                "url": url,
                "editable": editable,
            })
        return banks

    def _ensure_profile_is_outside_repository(self):
        repository_root = Path(__file__).resolve().parents[2]
        try:
            self.profile_dir.relative_to(repository_root)
        except ValueError:
            return
        raise CanvasQuestionBankError(
            "Canvas browser profile must be outside the repository."
        )

    def _playwright(self):
        if self.playwright_factory is not None:
            return self.playwright_factory()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise CanvasQuestionBankError(
                "Playwright is required for Canvas Question Bank renaming."
            ) from error
        return sync_playwright()

    def _create_rollback_directory(self):
        self.rollback_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        target = self.rollback_root / (
            f"{self.registry.course_code}-question-banks-{self.mode}-{self.language}-{timestamp}"
        )
        target.mkdir()
        return target

    @staticmethod
    def _normalize_name(value):
        value = VISIBLE_MARKER_RE.sub("", str(value or ""))
        return re.sub(r"\s+", " ", value).strip().casefold()

    @staticmethod
    def _write_json(path, payload):
        path = Path(path)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temp_name = output.name
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_name, path)
        except OSError as error:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise CanvasQuestionBankError(f"Unable to write Question Bank audit: {error}") from error

    @staticmethod
    def _coerce_registry(registry):
        try:
            if isinstance(registry, TranslationIdRegistry):
                return registry
            if isinstance(registry, Mapping):
                return TranslationIdRegistry.from_dict(registry)
            return TranslationIdRegistry.load(registry)
        except TranslationIdRegistryError as error:
            raise CanvasQuestionBankError(str(error)) from error

