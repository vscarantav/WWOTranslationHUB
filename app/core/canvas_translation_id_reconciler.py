"""Verification-first Canvas REST registration for Translation IDs."""

from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from core.translation_id_registry import (
    FILENAME_MARKER_RE,
    LANGUAGES,
    VISIBLE_MARKER_RE,
    TranslationIdRegistry,
    TranslationIdRegistryError,
)


APPROVAL_PHRASE = "APPLY TRANSLATION ID CHANGES"
SUPPORTED_API_TYPES = {
    "Page",
    "Assignment",
    "Quiz",
    "Discussion",
    "Announcement",
    "Syllabus",
    "File",
}


class CanvasTranslationIdError(RuntimeError):
    """Raised when safe Canvas planning or mutation cannot continue."""


def parse_canvas_course_url(course_url: str) -> Dict[str, str]:
    parsed = urlparse(str(course_url or "").strip())
    match = re.fullmatch(r"/courses/(\d+)/?", parsed.path.rstrip("/") or "/")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not match:
        raise CanvasTranslationIdError(
            "Canvas course URL must be a full URL ending in /courses/<numeric-id>."
        )
    return {
        "course_id": match.group(1),
        "origin": f"{parsed.scheme}://{parsed.netloc}",
        "domain": parsed.netloc.casefold(),
        "course_url": f"{parsed.scheme}://{parsed.netloc}/courses/{match.group(1)}",
    }


def append_visible_marker(content: str, translation_id: str) -> str:
    """Append one plain marker paragraph while preserving existing markup."""
    content = str(content or "")
    markers = {marker.upper() for marker in VISIBLE_MARKER_RE.findall(content)}
    if markers == {translation_id}:
        return content
    if markers:
        raise CanvasTranslationIdError(
            f"Content already contains a different Translation ID: {', '.join(sorted(markers))}."
        )
    marker_html = f"<p>TranslationID: {translation_id}</p>"
    if "</body" in content.casefold():
        match = re.search(r"</body\s*>", content, re.IGNORECASE)
        return content[: match.start()] + marker_html + content[match.start() :]
    return content + marker_html


def format_canvas_filename(filename: str, translation_id: str) -> str:
    """Insert the confirmed bracketed ID before the final extension."""
    filename = str(filename or "")
    markers = {marker.upper() for marker in FILENAME_MARKER_RE.findall(filename)}
    if markers == {translation_id}:
        return filename
    if markers:
        raise CanvasTranslationIdError(
            f"File name already contains a different Translation ID: {', '.join(sorted(markers))}."
        )
    stem, extension = os.path.splitext(filename)
    if not stem:
        raise CanvasTranslationIdError("Canvas file display name is empty.")
    return f"{stem} [{translation_id}]{extension}"


class CanvasTranslationIdReconciler:
    """Discover, dry-run, apply, verify, and record Canvas ID changes."""

    def __init__(
        self,
        registry: TranslationIdRegistry | Mapping[str, Any] | os.PathLike[str] | str,
        course_url: str,
        language: str,
        mode: str,
        token: Optional[str] = None,
        api_url: Optional[str] = None,
        request_func=None,
        rollback_root: Optional[os.PathLike[str] | str] = None,
        timeout: int = 30,
    ) -> None:
        self.registry = self._coerce_registry(registry)
        self.course = parse_canvas_course_url(course_url)
        self.language = str(language).upper()
        if self.language not in LANGUAGES:
            raise CanvasTranslationIdError(f"Unsupported registry language: {language}")
        if mode not in {"source-register", "target-reconcile"}:
            raise CanvasTranslationIdError(f"Unsupported reconciliation mode: {mode}")
        if mode == "source-register" and self.language != "EN":
            raise CanvasTranslationIdError("Source registration must update the EN instance.")
        if mode == "target-reconcile" and self.language == "EN":
            raise CanvasTranslationIdError("Target reconciliation requires PTBR, SPA, or FRA.")
        if (
            mode == "source-register"
            and self.registry.source_course_id
            and self.registry.source_course_id != self.course["course_id"]
        ):
            raise CanvasTranslationIdError(
                "The selected English course does not match the registry source course ID."
            )
        self.mode = mode
        self.token = (token or os.getenv("CANVAS_API_TOKEN", "")).strip()
        if not self.token:
            raise CanvasTranslationIdError("CANVAS_API_TOKEN is required for Canvas verification.")
        configured_api = (api_url or os.getenv("CANVAS_API_URL", "")).strip().rstrip("/")
        if not configured_api:
            raise CanvasTranslationIdError("CANVAS_API_URL is required for Canvas verification.")
        api_origin = urlparse(configured_api)
        if not api_origin.netloc or api_origin.netloc.casefold() != self.course["domain"]:
            raise CanvasTranslationIdError(
                "The selected Canvas course domain does not match CANVAS_API_URL."
            )
        self.api_origin = f"{api_origin.scheme or 'https'}://{api_origin.netloc}"
        self.request_func = request_func or requests.request
        self.rollback_root = Path(
            rollback_root or Path.cwd() / "Translation ID Rollbacks"
        ).resolve()
        self.timeout = timeout
        self._last_inventory = None
        self._last_plan = None

    def discover(self) -> Dict[str, List[Dict[str, Any]]]:
        """Read the exact selected course and all supported object collections."""
        course = self._request_json(
            "GET",
            f"/api/v1/courses/{self.course['course_id']}",
            params={"include[]": "syllabus_body"},
        )
        returned_id = str(course.get("id", ""))
        if returned_id != self.course["course_id"]:
            raise CanvasTranslationIdError(
                f"Canvas returned course {returned_id or 'unknown'} instead of {self.course['course_id']}."
            )
        required_permissions = self._required_permissions()
        permissions = self._request_json(
            "GET",
            f"/api/v1/courses/{self.course['course_id']}/permissions",
            params={"permissions[]": sorted(required_permissions)},
        )
        denied = sorted(
            permission
            for permission in required_permissions
            if permissions.get(permission) is not True
        )
        if denied:
            raise CanvasTranslationIdError(
                "The authenticated Canvas user lacks required permissions for the selected course: "
                + ", ".join(denied)
            )

        inventory = {
            "Course": [course],
            "Page": self._get_all(
                f"/api/v1/courses/{self.course['course_id']}/pages",
                params={"include[]": "body"},
            ),
            "Assignment": self._get_all(
                f"/api/v1/courses/{self.course['course_id']}/assignments"
            ),
            "Quiz": self._get_all(f"/api/v1/courses/{self.course['course_id']}/quizzes"),
            "Discussion": self._get_all(
                f"/api/v1/courses/{self.course['course_id']}/discussion_topics",
                params={"only_announcements": "false"},
            ),
            "Announcement": self._get_all(
                f"/api/v1/courses/{self.course['course_id']}/discussion_topics",
                params={"only_announcements": "true"},
            ),
            "File": self._get_all(f"/api/v1/courses/{self.course['course_id']}/files"),
            "Module": self._discover_modules(),
        }
        self._last_inventory = inventory
        return deepcopy(inventory)

    def plan(self, inventory=None) -> Dict[str, Any]:
        """Create a no-write classification for every active registry item."""
        inventory = deepcopy(inventory) if inventory is not None else self.discover()
        plans = []
        for item in self.registry.items:
            if item.get("retired"):
                plans.append(self._unsupported_plan(item, "Unmatched", "Registry item is retired."))
                continue
            if self.mode == "source-register" and item.get("source_present") is False:
                plans.append(
                    self._unsupported_plan(
                        item,
                        "Source Absent",
                        "This target-specific packaged item has no English-master instance.",
                    )
                )
                continue
            item_type = item["item_type"]
            if item_type not in SUPPORTED_API_TYPES:
                plans.append(
                    self._unsupported_plan(
                        item,
                        "Not API Managed",
                        "This logical type is audited from package or module evidence.",
                    )
                )
                continue
            live_items = inventory.get("Course" if item_type == "Syllabus" else item_type, [])
            matches = self._match_live_items(item, live_items)
            if len(matches) != 1:
                detail = (
                    "No exact live item match was found."
                    if not matches
                    else f"{len(matches)} exact live item matches were found."
                )
                plans.append(self._unsupported_plan(item, "Unmatched", detail))
                continue
            live = matches[0]
            try:
                plan = self._classify_live_item(item, live, inventory)
            except CanvasTranslationIdError as error:
                plan = self._unsupported_plan(item, "Conflict", str(error), live=live)
            plans.append(plan)

        summary = {}
        for plan in plans:
            summary[plan["status"]] = summary.get(plan["status"], 0) + 1
        result = {
            "mode": self.mode,
            "language": self.language,
            "course_url": self.course["course_url"],
            "course_id": self.course["course_id"],
            "generated_at": datetime.now().astimezone().isoformat(),
            "summary": summary,
            "changes": plans,
        }
        self._last_inventory = inventory
        self._last_plan = result
        return deepcopy(result)

    def apply(self, plan: Mapping[str, Any], approval: str) -> Dict[str, Any]:
        """Apply only Missing changes after exact approval and verify each write."""
        if approval != APPROVAL_PHRASE:
            raise CanvasTranslationIdError(
                f"Live writes require the exact approval phrase: {APPROVAL_PHRASE}"
            )
        if str(plan.get("course_id")) != self.course["course_id"]:
            raise CanvasTranslationIdError("Dry-run plan course does not match this reconciler.")
        if plan.get("mode") != self.mode or plan.get("language") != self.language:
            raise CanvasTranslationIdError("Dry-run plan mode/language does not match this reconciler.")
        blockers = [
            change
            for change in plan.get("changes", [])
            if change.get("status") in {"Conflict", "Unmatched"}
            and change.get("item_type") in SUPPORTED_API_TYPES
        ]
        if blockers:
            raise CanvasTranslationIdError(
                "Live writes are blocked until every supported item conflict/unmatched result is resolved."
            )

        rollback_dir = self._create_rollback_directory()
        self.registry.save(rollback_dir / "registry-before.json")
        self._write_json(rollback_dir / "dry-run-plan.json", plan)
        results = []
        for change in plan.get("changes", []):
            if change.get("status") != "Missing":
                results.append({**deepcopy(change), "write_result": "Skipped"})
                continue
            response = self._request_json(
                "PUT",
                change["endpoint"],
                data=change["payload"],
            )
            verify_kwargs = (
                {"params": {"include[]": "syllabus_body"}}
                if change["item_type"] == "Syllabus"
                else {}
            )
            verified = self._request_json("GET", change["verify_endpoint"], **verify_kwargs)
            verified_value = self._live_value(change["item_type"], verified)
            expected_value = change["proposed_value"]
            if verified_value != expected_value:
                self._write_json(
                    rollback_dir / "failed-verification.json",
                    {
                        "change": change,
                        "put_response": response,
                        "verified_response": verified,
                    },
                )
                raise CanvasTranslationIdError(
                    f"Canvas did not verify {change['translation_id']}; write run stopped."
                )
            self.registry.update_instance(
                change["translation_id"],
                self.language,
                course_id=self.course["course_id"],
                content_id=str(self._live_id(change["item_type"], verified) or ""),
                module_item_id=change.get("module_item_id"),
                title=self._live_title(change["item_type"], verified),
                url=self._live_url(verified),
                presence="present",
                id_status="verified",
            )
            results.append({**deepcopy(change), "write_result": "Verified"})
            self._write_json(
                rollback_dir / f"{change['translation_id']}.json",
                {
                    "translation_id": change["translation_id"],
                    "endpoint": change["endpoint"],
                    "original_value": change["original_value"],
                    "proposed_value": expected_value,
                    "put_response": response,
                    "verified_response": verified,
                },
            )

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

    def restore_change(self, change: Mapping[str, Any], approval: str) -> Dict[str, Any]:
        """Restore one recorded value and verify it; never bulk-restore implicitly."""
        if approval != APPROVAL_PHRASE:
            raise CanvasTranslationIdError("Restoration requires explicit live-write approval.")
        self._request_json("PUT", change["endpoint"], data=change["rollback_payload"])
        verify_kwargs = (
            {"params": {"include[]": "syllabus_body"}}
            if change["item_type"] == "Syllabus"
            else {}
        )
        verified = self._request_json("GET", change["verify_endpoint"], **verify_kwargs)
        actual = self._live_value(change["item_type"], verified)
        if actual != change["original_value"]:
            raise CanvasTranslationIdError(
                f"Canvas did not verify restoration for {change['translation_id']}."
            )
        return verified

    def _classify_live_item(self, item, live, inventory):
        item_type = item["item_type"]
        translation_id = item["translation_id"]
        original = self._live_value(item_type, live)
        if item_type == "File":
            markers = {value.upper() for value in FILENAME_MARKER_RE.findall(original)}
            proposed = format_canvas_filename(original, translation_id)
            folder_id = live.get("folder_id")
            collisions = [
                other
                for other in inventory.get("File", [])
                if str(other.get("id")) != str(live.get("id"))
                and other.get("folder_id") == folder_id
                and str(other.get("display_name") or other.get("filename") or "").casefold()
                == proposed.casefold()
            ]
            if collisions:
                raise CanvasTranslationIdError(
                    f"File rename would collide in Canvas folder {folder_id}."
                )
        else:
            markers = {value.upper() for value in VISIBLE_MARKER_RE.findall(original)}
            proposed = append_visible_marker(original, translation_id)

        if markers == {translation_id}:
            status = "Correct"
        elif markers:
            status = "Conflict"
        else:
            status = "Missing"
        endpoint, verify_endpoint, payload, rollback_payload = self._write_contract(
            item_type, live, proposed, original
        )
        module_item_id = self._module_item_id(item, inventory)
        plan = {
            "translation_id": translation_id,
            "item_type": item_type,
            "source_title": item["source_title"],
            "status": status,
            "detail": "" if status != "Conflict" else "A different Translation ID is present.",
            "live_id": str(self._live_id(item_type, live) or ""),
            "live_title": self._live_title(item_type, live),
            "live_url": self._live_url(live),
            "module_item_id": module_item_id,
            "folder_id": live.get("folder_id"),
            "original_value": original,
            "proposed_value": proposed,
            "endpoint": endpoint,
            "verify_endpoint": verify_endpoint,
            "payload": payload,
            "rollback_payload": rollback_payload,
        }
        instance = next(
            entry for entry in self.registry.items if entry["translation_id"] == translation_id
        )["instances"][self.language]
        instance.update(
            {
                "course_id": self.course["course_id"],
                "content_id": plan["live_id"],
                "module_item_id": module_item_id,
                "title": plan["live_title"],
                "url": plan["live_url"],
                "presence": "present",
                "id_status": status.casefold(),
            }
        )
        return plan

    def _match_live_items(self, item, live_items):
        if item["item_type"] == "Syllabus":
            return list(live_items[:1])
        expected_titles = {
            self._normalize_title(item.get("source_title", "")),
            self._normalize_title(item.get("instances", {}).get("EN", {}).get("title", "")),
            self._normalize_title(item.get("instances", {}).get(self.language, {}).get("title", "")),
        }
        expected_titles.discard("")
        title_matches = [
            live
            for live in live_items
            if self._normalize_title(self._live_title(item["item_type"], live)) in expected_titles
        ]
        if len(title_matches) == 1:
            return title_matches
        if item["item_type"] == "File" and len(title_matches) > 1:
            untagged_exact = [
                live
                for live in title_matches
                if not FILENAME_MARKER_RE.search(self._live_title("File", live))
                and self._live_title("File", live).strip().casefold()
                == str(item.get("source_title", "")).strip().casefold()
            ]
            if len(untagged_exact) == 1:
                return untagged_exact
        if item["item_type"] == "Page":
            page_paths = [
                path for path in item.get("package_paths", []) if path.startswith("wiki_content/")
            ]
            slugs = {Path(path).stem.casefold() for path in page_paths}
            slug_matches = [
                live
                for live in live_items
                if str(live.get("url", "")).casefold() in slugs
            ]
            if len(slug_matches) == 1:
                return slug_matches
        return title_matches

    def _write_contract(self, item_type, live, proposed, original):
        course_id = self.course["course_id"]
        if item_type == "Page":
            live_key = live.get("url") or live.get("page_id")
            endpoint = f"/api/v1/courses/{course_id}/pages/{live_key}"
            return endpoint, endpoint, {"wiki_page[body]": proposed}, {"wiki_page[body]": original}
        if item_type == "Assignment":
            endpoint = f"/api/v1/courses/{course_id}/assignments/{live['id']}"
            return endpoint, endpoint, {"assignment[description]": proposed}, {"assignment[description]": original}
        if item_type == "Quiz":
            endpoint = f"/api/v1/courses/{course_id}/quizzes/{live['id']}"
            return endpoint, endpoint, {"quiz[description]": proposed}, {"quiz[description]": original}
        if item_type in {"Discussion", "Announcement"}:
            endpoint = f"/api/v1/courses/{course_id}/discussion_topics/{live['id']}"
            return endpoint, endpoint, {"message": proposed}, {"message": original}
        if item_type == "Syllabus":
            endpoint = f"/api/v1/courses/{course_id}"
            return endpoint, endpoint, {"course[syllabus_body]": proposed}, {"course[syllabus_body]": original}
        if item_type == "File":
            endpoint = f"/api/v1/files/{live['id']}"
            return endpoint, endpoint, {"name": proposed}, {"name": original}
        raise CanvasTranslationIdError(f"No Canvas write contract for {item_type}.")

    def _unsupported_plan(self, item, status, detail, live=None):
        live = live or {}
        return {
            "translation_id": item["translation_id"],
            "item_type": item["item_type"],
            "source_title": item["source_title"],
            "status": status,
            "detail": detail,
            "live_id": str(self._live_id(item["item_type"], live) or ""),
            "live_title": self._live_title(item["item_type"], live),
            "live_url": self._live_url(live),
            "original_value": "",
            "proposed_value": "",
        }

    def _module_item_id(self, item, inventory):
        manifest_id = item.get("manifest_identifier")
        matches = []
        for module in inventory.get("Module", []):
            for module_item in module.get("items", []):
                if manifest_id and str(module_item.get("content_id", "")) == str(manifest_id):
                    matches.append(module_item)
                elif self._normalize_title(module_item.get("title", "")) == self._normalize_title(item.get("source_title", "")):
                    matches.append(module_item)
        ids = {str(match.get("id")) for match in matches if match.get("id") is not None}
        return next(iter(ids)) if len(ids) == 1 else None

    def _discover_modules(self):
        modules = self._get_all(f"/api/v1/courses/{self.course['course_id']}/modules")
        for module in modules:
            module["items"] = self._get_all(
                f"/api/v1/courses/{self.course['course_id']}/modules/{module['id']}/items"
            )
        return modules

    def _required_permissions(self):
        permission_by_type = {
            "Page": "manage_wiki_update",
            "Assignment": "manage_assignments_edit",
            "Quiz": "manage_assignments_edit",
            "Discussion": "moderate_forum",
            "Announcement": "moderate_forum",
            "Syllabus": "manage_course_content_edit",
            "File": "manage_files_edit",
        }
        return {
            permission_by_type[item["item_type"]]
            for item in self.registry.items
            if not item.get("retired") and item.get("item_type") in permission_by_type
        }

    def _get_all(self, endpoint, params=None):
        params = dict(params or {})
        params.setdefault("per_page", 100)
        results = []
        next_url = endpoint
        while next_url:
            response = self._request("GET", next_url, params=params)
            payload = self._decode_json(response)
            if not isinstance(payload, list):
                raise CanvasTranslationIdError(f"Canvas list endpoint returned invalid data: {endpoint}")
            results.extend(payload)
            next_url = self._next_link(response)
            params = None
        return results

    def _request_json(self, method, endpoint, **kwargs):
        return self._decode_json(self._request(method, endpoint, **kwargs))

    def _request(self, method, endpoint, **kwargs):
        url = endpoint if str(endpoint).startswith("http") else self.api_origin + str(endpoint)
        if urlparse(url).netloc.casefold() != self.course["domain"]:
            raise CanvasTranslationIdError("Canvas pagination/write URL changed domains.")
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.request_func(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as error:
            raise CanvasTranslationIdError(f"Canvas request failed: {error}") from error
        status_code = getattr(response, "status_code", 0)
        if not 200 <= status_code < 300:
            raise CanvasTranslationIdError(
                f"Canvas {method} request failed with HTTP {status_code}."
            )
        return response

    @staticmethod
    def _decode_json(response):
        try:
            return response.json()
        except (ValueError, AttributeError) as error:
            raise CanvasTranslationIdError("Canvas returned invalid JSON.") from error

    @staticmethod
    def _next_link(response):
        links = getattr(response, "links", None) or {}
        if links.get("next", {}).get("url"):
            return links["next"]["url"]
        return None

    @staticmethod
    def _normalize_title(value):
        value = VISIBLE_MARKER_RE.sub("", str(value or ""))
        value = FILENAME_MARKER_RE.sub("", value)
        value = re.sub(r"\s+(\.[^.\s]+)$", r"\1", value)
        return re.sub(r"\s+", " ", value).strip().casefold()

    @staticmethod
    def _live_title(item_type, live):
        if item_type == "Page":
            return str(live.get("title") or "")
        if item_type == "Assignment":
            return str(live.get("name") or "")
        if item_type in {"Quiz", "Discussion", "Announcement"}:
            return str(live.get("title") or "")
        if item_type == "Syllabus":
            return str(live.get("name") or live.get("course_code") or "Course Syllabus")
        if item_type == "File":
            return str(live.get("display_name") or live.get("filename") or "")
        return str(live.get("title") or live.get("name") or "")

    @staticmethod
    def _live_value(item_type, live):
        if item_type == "Page":
            return str(live.get("body") or "")
        if item_type == "Assignment":
            return str(live.get("description") or "")
        if item_type == "Quiz":
            return str(live.get("description") or "")
        if item_type in {"Discussion", "Announcement"}:
            return str(live.get("message") or "")
        if item_type == "Syllabus":
            return str(live.get("syllabus_body") or "")
        if item_type == "File":
            return str(live.get("display_name") or live.get("filename") or "")
        return ""

    @staticmethod
    def _live_id(item_type, live):
        if item_type == "Page":
            return live.get("page_id") or live.get("url")
        return live.get("id")

    @staticmethod
    def _live_url(live):
        return str(live.get("html_url") or live.get("url") or "")

    def _create_rollback_directory(self):
        self.rollback_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        target = self.rollback_root / (
            f"{self.registry.course_code}-{self.mode}-{self.language}-{timestamp}"
        )
        target.mkdir()
        return target

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
            raise CanvasTranslationIdError(f"Unable to write rollback artifact: {error}") from error

    @staticmethod
    def _coerce_registry(registry):
        try:
            if isinstance(registry, TranslationIdRegistry):
                return registry
            if isinstance(registry, Mapping):
                return TranslationIdRegistry.from_dict(registry)
            return TranslationIdRegistry.load(registry)
        except TranslationIdRegistryError as error:
            raise CanvasTranslationIdError(str(error)) from error

