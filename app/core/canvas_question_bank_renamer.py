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


CANVAS_LOGIN_URL = "https://byui.instructure.com/login/canvas"
CANVAS_LOGIN_SUCCESS_URL = "https://byui.instructure.com/?login_success=1"
CANVAS_ACCOUNT_BOOTSTRAP_URL = "https://byupw.instructure.com/accounts/139"


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
                self._open_question_banks_after_login(page, login_checkpoint)
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
                self._open_question_banks_after_login(page, login_checkpoint)
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

    def _open_question_banks_after_login(self, page, login_checkpoint) -> str:
        """Follow the required BYU-I login, account bootstrap, and course order."""
        if login_checkpoint is None:
            raise CanvasQuestionBankError(
                "A user-controlled Canvas/SSO login checkpoint is required."
            )
        manage_url = self.course["course_url"] + "/question_banks"
        page.goto(CANVAS_LOGIN_URL, wait_until="domcontentloaded")
        login_attempt = 0
        while self._live_page_url(page) != CANVAS_LOGIN_SUCCESS_URL:
            login_attempt += 1
            details = (
                "Complete login at https://byui.instructure.com/login/canvas. "
                "The HUB does not read or store your password. Click OK only "
                "after the browser reaches "
                "https://byui.instructure.com/?login_success=1. The HUB will "
                "verify that exact successful-login URL, then open Canvas account "
                "139 before proceeding to the course Question Banks page."
            )
            if login_attempt > 1:
                details = (
                    "Login was not verified because the browser has not reached "
                    "https://byui.instructure.com/?login_success=1. Complete login "
                    "in the still-open browser, then click OK to check again."
                )
            if login_checkpoint(
                {
                    "action": "Complete BYU-Idaho Canvas login in the visible browser",
                    "url": CANVAS_LOGIN_URL,
                    "success_url": CANVAS_LOGIN_SUCCESS_URL,
                    "next_url": CANVAS_ACCOUNT_BOOTSTRAP_URL,
                    "attempt": login_attempt,
                    "details": details,
                }
            ) is False:
                raise CanvasQuestionBankError("Canvas login checkpoint was cancelled.")

        page.goto(CANVAS_ACCOUNT_BOOTSTRAP_URL, wait_until="domcontentloaded")
        page.goto(manage_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        if "/login" in self._live_page_url(page).casefold():
            raise CanvasQuestionBankError(
                "Canvas returned to a login page after the account 139 bootstrap."
            )
        return manage_url

    @staticmethod
    def _live_page_url(page) -> str:
        """Query the browser directly because page.url can be stale after a Tk wait."""
        evaluate = getattr(page, "evaluate", None)
        if callable(evaluate):
            return str(evaluate("window.location.href") or "").strip()
        return str(getattr(page, "url", "") or "").strip()

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

    @staticmethod
    def _element_text(locator) -> str:
        if locator is None or locator.count() == 0:
            return ""
        text_func = getattr(locator, "text_content", None) or getattr(locator, "inner_text", None)
        if callable(text_func):
            try:
                return str(text_func() or "").strip()
            except Exception:
                return ""
        return ""

    @staticmethod
    def _wait_page(page, ms: int) -> None:
        wait_func = getattr(page, "wait_for_timeout", None)
        if callable(wait_func):
            wait_func(ms)

    def _rename_one(self, page, change):
        manage_url = self.course["course_url"] + "/question_banks"
        if not self._live_page_url(page).startswith(manage_url):
            page.goto(manage_url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")

        bank_id = str(change.get("live_id") or "").strip()
        bank_container = None
        if bank_id:
            candidate = page.locator(f"#question_bank_{bank_id}")
            if candidate.count() > 0:
                bank_container = candidate.first
            else:
                candidate = page.locator(f'.question_bank:has(a[href*="/question_banks/{bank_id}"])')
                if candidate.count() > 0:
                    bank_container = candidate.first
        if bank_container is None:
            old_name = change.get("old_name") or change.get("source_title") or ""
            if old_name:
                candidate = page.locator(f'.question_bank:has(a.title:text-is("{old_name}"))')
                if candidate.count() > 0:
                    bank_container = candidate.first

        if bank_container is None or bank_container.count() == 0:
            raise CanvasQuestionBankError(
                f"Question Bank container not found on manage page for {change['translation_id']}."
            )

        title_elem = bank_container.locator("a.title")
        initial_text = self._element_text(title_elem)
        if change["new_name"] in initial_text:
            return

        edit_control = bank_container.locator(
            ".edit_bank_link, button:has(.icon-edit), button[title*='Edit'], a.edit_bank_link"
        )
        if edit_control.count() == 0:
            raise CanvasQuestionBankError(
                f"Canvas edit-name control is missing for {change['translation_id']}."
            )
        edit_control.first.click()

        # Canvas opens an inline form, typically with id 'edit_bank_form'
        form = bank_container.locator("#edit_bank_form, form")
        if form.count() == 0:
            form = page.locator("#edit_bank_form, form.edit_bank_form")
        if form.count() > 0:
            try:
                form.first.wait_for(state="visible", timeout=5000)
            except Exception:
                pass

        # Locate the text input for the title
        name_input = None
        if form.count() > 0:
            inputs = form.first.locator(
                'input[type="text"], input[name*="title"], input[name*="name"], input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
            )
            if inputs.count() > 0:
                name_input = inputs.first
        if name_input is None or name_input.count() == 0:
            name_input = bank_container.locator(
                'input[type="text"], input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
            ).first

        if name_input is None or name_input.count() == 0:
            raise CanvasQuestionBankError(
                f"Canvas bank-name field is missing for {change['translation_id']}."
            )

        name_input.wait_for(state="visible", timeout=1500)
        name_input.fill(change["new_name"])

        # Check for submit button or press Enter
        submit_button = None
        if form.count() > 0:
            candidates = form.first.locator(
                'button[type="submit"], input[type="submit"], button.Button--primary, button:has-text("Save"), button:has-text("Update")'
            )
            if candidates.count() > 0 and candidates.first.is_visible():
                submit_button = candidates.first

        if submit_button:
            submit_button.click()
        else:
            name_input.press("Enter")

        # Wait for form to close / disappear
        if form.count() > 0:
            try:
                form.first.wait_for(state="hidden", timeout=1500)
            except Exception:
                pass

        # Verify update: allow Canvas to complete the asynchronous write and update the DOM
        verified = False
        title_elem = bank_container.locator("a.title")
        for _ in range(30):
            current_text = self._element_text(title_elem)
            if change["new_name"] in current_text:
                verified = True
                break
            self._wait_page(page, 100)

        if not verified:
            # If not yet reflected in DOM, wait briefly and reload to verify
            self._wait_page(page, 250)
            page.reload(wait_until="domcontentloaded")
            for _ in range(15):
                names = [bank["name"] for bank in self._enumerate_page_banks(page)]
                body_elem = page.locator("body")
                body_text = self._element_text(body_elem)
                if change["new_name"] in names or change["new_name"] in body_text:
                    verified = True
                    break
                self._wait_page(page, 100)

        if not verified:
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

