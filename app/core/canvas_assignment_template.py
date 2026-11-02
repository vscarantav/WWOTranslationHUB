import difflib
import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests
from lxml import etree


W07_TEMPLATE_BASE_URL = "https://byupw.instructure.com"
W07_TEMPLATE_COURSE_ID = "11564"
W07_TEMPLATE_ASSIGNMENT_ID = "816997"


def _normalized_words(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def is_w07_end_of_course_evaluation(value: str) -> bool:
    """Recognize common punctuation and wording variants of the W07 assignment."""
    normalized = _normalized_words(value)
    if not normalized:
        return False

    words = set(normalized.split())
    has_week_7 = bool(re.search(r"\b(?:w|week)\s*0?7\b", normalized))
    has_course_evaluation = (
        "course" in words and bool(words.intersection({"evaluation", "survey"}))
    )
    if has_week_7 and has_course_evaluation:
        return True

    canonical = "w07 end of course evaluation"
    similarity = difflib.SequenceMatcher(None, normalized, canonical).ratio()
    return has_week_7 and similarity >= 0.72


def _local_name(element) -> str:
    return etree.QName(element).localname


def _direct_child(parent, name: str):
    return next(
        (child for child in parent if _local_name(child) == name),
        None,
    )


def _set_direct_child(parent, name: str, value):
    child = _direct_child(parent, name)
    if child is None:
        namespace = etree.QName(parent).namespace
        qualified_name = f"{{{namespace}}}{name}" if namespace else name
        child = etree.SubElement(parent, qualified_name)
    child.text = None if value is None else str(value)
    return child


def _boolean(value) -> str:
    return "true" if bool(value) else "false"


def _write_xml(tree, path: Path):
    tree.write(
        str(path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


@dataclass(frozen=True)
class W07TemplateInstallation:
    identifier: str
    title: str
    assignment_settings_path: Path
    description_path: Path
    new_tab: bool

    @property
    def protected_paths(self):
        return {
            self.assignment_settings_path.resolve(),
            self.description_path.resolve(),
        }


class CanvasAssignmentTemplateClient:
    def __init__(
        self,
        base_url=W07_TEMPLATE_BASE_URL,
        course_id=W07_TEMPLATE_COURSE_ID,
        assignment_id=W07_TEMPLATE_ASSIGNMENT_ID,
        token=None,
        request_get=None,
        timeout=30,
    ):
        self.base_url = base_url.rstrip("/")
        self.course_id = str(course_id)
        self.assignment_id = str(assignment_id)
        self.token = token
        self.request_get = request_get or requests.get
        self.timeout = timeout

    @property
    def assignment_url(self):
        return (
            f"{self.base_url}/api/v1/courses/{self.course_id}"
            f"/assignments/{self.assignment_id}"
        )

    def fetch(self) -> dict:
        token = self.token or os.getenv("CANVAS_API_TOKEN")
        if not token:
            raise RuntimeError(
                "CANVAS_API_TOKEN is required to fetch the approved W07 "
                "Portuguese assignment."
            )

        try:
            response = self.request_get(
                self.assignment_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            assignment = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(
                "Unable to fetch the approved W07 Portuguese assignment "
                f"from Canvas: {exc}"
            ) from exc

        if not isinstance(assignment, dict):
            raise RuntimeError(
                "Canvas returned an invalid W07 Portuguese assignment payload."
            )
        if not str(assignment.get("name") or "").strip():
            raise RuntimeError(
                "Canvas returned the W07 Portuguese assignment without a name."
            )

        submission_types = assignment.get("submission_types") or []
        external_tool = assignment.get("external_tool_tag_attributes") or {}
        if "external_tool" in submission_types and not external_tool.get("url"):
            raise RuntimeError(
                "Canvas returned the W07 Portuguese external-tool assignment "
                "without its launch URL."
            )
        return assignment


class W07AssignmentTemplateInstaller:
    def __init__(self, client=None):
        self.client = client or CanvasAssignmentTemplateClient()

    @staticmethod
    def _assignment_title(settings_path: Path) -> str:
        tree = etree.parse(str(settings_path))
        title = _direct_child(tree.getroot(), "title")
        return title.text.strip() if title is not None and title.text else ""

    @staticmethod
    def _description_file(assignment_dir: Path) -> Path:
        html_files = sorted(
            path
            for path in assignment_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in {".html", ".htm"}
        )
        if len(html_files) == 1:
            return html_files[0]

        matching_files = [
            path
            for path in html_files
            if is_w07_end_of_course_evaluation(path.stem)
        ]
        if len(matching_files) == 1:
            return matching_files[0]
        raise RuntimeError(
            "The W07 assignment directory must contain one identifiable HTML "
            "description file."
        )

    def find_assignment(self, course_root) -> tuple[Path, Path]:
        course_root = Path(course_root)
        matches = []
        for settings_path in course_root.rglob("assignment_settings.xml"):
            labels = [settings_path.parent.name]
            try:
                labels.append(self._assignment_title(settings_path))
            except (OSError, etree.XMLSyntaxError):
                continue

            html_files = [
                path
                for path in settings_path.parent.iterdir()
                if path.is_file() and path.suffix.casefold() in {".html", ".htm"}
            ]
            labels.extend(path.stem for path in html_files)
            if any(is_w07_end_of_course_evaluation(label) for label in labels):
                matches.append(
                    (settings_path, self._description_file(settings_path.parent))
                )

        if not matches:
            raise RuntimeError(
                "No W07 End-of-Course Evaluation assignment was found in the "
                "English course package."
            )
        if len(matches) > 1:
            paths = ", ".join(str(settings) for settings, _html in matches)
            raise RuntimeError(
                "Multiple possible W07 End-of-Course Evaluation assignments were "
                f"found; the package is ambiguous: {paths}"
            )
        return matches[0]

    @staticmethod
    def _apply_assignment_settings(settings_path: Path, assignment: dict) -> str:
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(settings_path), parser)
        root = tree.getroot()
        identifier = str(root.get("identifier") or "").strip()
        if not identifier:
            raise RuntimeError(
                "The W07 assignment_settings.xml is missing its package identifier."
            )

        external_tool = assignment.get("external_tool_tag_attributes") or {}
        submission_types = assignment.get("submission_types") or []
        due_at = assignment.get("due_at")

        values = {
            "title": assignment["name"],
            "due_at": due_at,
            "lock_at": assignment.get("lock_at"),
            "unlock_at": assignment.get("unlock_at"),
            "all_day_date": None if not due_at else assignment.get("all_day_date"),
            "workflow_state": (
                assignment.get("workflow_state")
                or ("published" if assignment.get("published") else "unpublished")
            ),
            "allowed_extensions": "",
            "has_group_category": _boolean(assignment.get("group_category_id")),
            "points_possible": assignment.get("points_possible", 0),
            "grading_type": assignment.get("grading_type") or "points",
            "all_day": _boolean(assignment.get("all_day", False) if due_at else False),
            "submission_types": ",".join(str(value) for value in submission_types),
            "peer_review_count": assignment.get("peer_review_count") or 0,
            "peer_reviews": _boolean(assignment.get("peer_reviews")),
            "automatic_peer_reviews": _boolean(
                assignment.get("automatic_peer_reviews")
            ),
            "anonymous_peer_reviews": _boolean(
                assignment.get("anonymous_peer_reviews")
            ),
            "grade_group_students_individually": _boolean(
                assignment.get("grade_group_students_individually")
            ),
            "omit_from_final_grade": _boolean(
                assignment.get("omit_from_final_grade")
            ),
            "hide_in_gradebook": _boolean(assignment.get("hide_in_gradebook")),
            "intra_group_peer_reviews": _boolean(
                assignment.get("intra_group_peer_reviews")
            ),
            "only_visible_to_overrides": _boolean(
                assignment.get("only_visible_to_overrides")
            ),
            "post_to_sis": _boolean(assignment.get("post_to_sis")),
            "moderated_grading": _boolean(assignment.get("moderated_grading")),
            "grader_count": assignment.get("grader_count") or 0,
            "grader_comments_visible_to_graders": _boolean(
                assignment.get("grader_comments_visible_to_graders", True)
            ),
            "anonymous_grading": _boolean(assignment.get("anonymous_grading")),
            "graders_anonymous_to_graders": _boolean(
                assignment.get("graders_anonymous_to_graders")
            ),
            "grader_names_visible_to_final_grader": _boolean(
                assignment.get("grader_names_visible_to_final_grader", True)
            ),
            "anonymous_instructor_annotations": _boolean(
                assignment.get("anonymous_instructor_annotations")
            ),
            "external_tool_external_identifier": external_tool.get("content_id"),
            "external_tool_url": external_tool.get("url"),
            "external_tool_data_json": json.dumps(
                external_tool.get("external_data") or "",
                ensure_ascii=False,
            ),
            "external_tool_new_tab": _boolean(external_tool.get("new_tab")),
        }
        for name, value in values.items():
            _set_direct_child(root, name, value)

        overrides = _direct_child(root, "assignment_overrides")
        if overrides is not None:
            for child in list(overrides):
                overrides.remove(child)

        lockdown_settings = _direct_child(root, "lockdown_browser_settings")
        if lockdown_settings is not None:
            lockdown_settings.text = json.dumps(
                {
                    "require_lockdown_browser": bool(
                        assignment.get("require_lockdown_browser")
                    )
                },
                separators=(",", ":"),
            )

        post_policy = _direct_child(root, "post_policy")
        if post_policy is not None:
            _set_direct_child(
                post_policy,
                "post_manually",
                _boolean(assignment.get("post_manually")),
            )

        _write_xml(tree, settings_path)
        return identifier

    @staticmethod
    def _apply_description(description_path: Path, assignment: dict):
        title = html.escape(str(assignment["name"]), quote=False)
        description = assignment.get("description") or ""
        content = (
            "<html>\n<head>\n"
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
            f"<title>Assignment: {title}</title>\n"
            "</head>\n<body>\n"
            f"{description}\n"
            "</body>\n</html>\n"
        )
        description_path.write_text(content, encoding="utf-8")

    def install(self, course_root) -> W07TemplateInstallation:
        settings_path, description_path = self.find_assignment(course_root)
        assignment = self.client.fetch()
        identifier = self._apply_assignment_settings(settings_path, assignment)
        self._apply_description(description_path, assignment)
        external_tool = assignment.get("external_tool_tag_attributes") or {}
        return W07TemplateInstallation(
            identifier=identifier,
            title=str(assignment["name"]).strip(),
            assignment_settings_path=settings_path,
            description_path=description_path,
            new_tab=bool(external_tool.get("new_tab")),
        )

    @staticmethod
    def enforce_package_references(
        course_root,
        installation: W07TemplateInstallation,
    ) -> int:
        updated_files = 0
        candidates = (
            Path(course_root) / "imsmanifest.xml",
            Path(course_root) / "course_settings" / "module_meta.xml",
        )
        for path in candidates:
            if not path.exists():
                continue
            parser = etree.XMLParser(remove_blank_text=False)
            tree = etree.parse(str(path), parser)
            changed = False
            for item in tree.getroot().iter():
                if _local_name(item) != "item":
                    continue
                child_reference = _direct_child(item, "identifierref")
                reference = item.get("identifierref") or (
                    child_reference.text
                    if child_reference is not None and child_reference.text
                    else ""
                )
                if reference.strip() != installation.identifier:
                    continue
                _set_direct_child(item, "title", installation.title)
                new_tab = _direct_child(item, "new_tab")
                if new_tab is not None:
                    new_tab.text = _boolean(installation.new_tab)
                changed = True
            if changed:
                _write_xml(tree, path)
                updated_files += 1
        return updated_files
