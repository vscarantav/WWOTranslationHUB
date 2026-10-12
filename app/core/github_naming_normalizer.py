import posixpath
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup


class GitHubNamingNormalizer:
    """Apply the canonical PT-BR course-title structure after translation."""

    ENGLISH_TO_PORTUGUESE_HEADINGS = {
        "activity instructions": "Instruções da Atividade",
        "assignment": "Tarefa",
        "audit and submission": "Auditoria e Envio",
        "check your understanding": "Avalie Seu Conhecimento",
        "course home": "Página Inicial do Curso",
        "exam instructions": "Instruções para a Prova",
        "getting help": "Obtendo Ajuda",
        "instructions": "Instruções",
        "learning activities": "Atividades de Aprendizagem",
        "learning activity": "Atividade de Aprendizagem",
        "optional resources": "Recursos Opcionais",
        "overview": "Visão Geral",
        "page audit": "Auditoria de Páginas",
        "prepare": "Preparação",
        "project requirements": "Requisitos do Projeto",
        "submission": "Envio",
        "task": "Tarefa",
        "testing": "Testes",
    }

    KIND_LABELS = {
        "learning_activity": "Atividade de Aprendizagem",
        "learning_activities": "Atividades de Aprendizagem",
        "assignment": "Tarefa",
        "project": "Projeto",
        "setup": "Configuração",
        "exam": "Prova",
        "final_exam": "Prova Final",
        "audit": "Auditoria de Páginas",
    }

    _WEEK_CODE = re.compile(r"\b[WS](\d{1,2})\b", re.IGNORECASE)
    _WEEK_NAME = re.compile(r"\b(?:week|semana)\s*(\d{1,2})\b", re.IGNORECASE)
    _COURSE_CODE = re.compile(r"\b[A-Z]{2,6}\s*\d{2,4}\b")
    _LEADING_WEEK = re.compile(
        r"^\s*(?:[WS]\s*0?\d{1,2}|(?:week|semana)\s+0?\d{1,2})"
        r"\s*(?:[-–—|:]\s*)?",
        re.IGNORECASE,
    )
    _KIND_PREFIXES = {
        "learning_activity": r"learning\s+activity|atividade\s+de\s+aprendizagem",
        "learning_activities": r"learning\s+activities|atividades\s+de\s+aprendizagem",
        "assignment": r"assignment|tarefa",
        "project": r"project|projeto",
        "setup": r"setup|configura(?:ç|c)[aã]o",
        "exam": r"exam|prova",
        "final_exam": r"final\s+exam|prova\s+final",
        "audit": r"page\s+audits?|auditoria\s+de\s+p[aá]ginas",
    }

    @staticmethod
    def _clean_text(value):
        return re.sub(r"\s+", " ", value or "").strip()

    @classmethod
    def _week_number(cls, source_text, relative_path):
        path_match = re.search(r"(?:^|/)week[-_]?0?(\d{1,2})(?:/|$)", relative_path, re.IGNORECASE)
        if path_match:
            return int(path_match.group(1))
        for pattern in (cls._WEEK_CODE, cls._WEEK_NAME):
            match = pattern.search(source_text)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _source_kind(source_text, relative_path):
        text = source_text.casefold()
        path = relative_path.casefold().replace("\\", "/")
        name = PurePosixPath(path).name
        if "/audit/" in f"/{path}" or "page audit" in text:
            return "audit"
        if name in {"index.html", "index.htm", "index.md", "index.markdown", "index.mdx"} and re.search(
            r"(?:^|/)week[-_]?\d{1,2}/", path
        ):
            return "week_index"
        if "learning activities" in text:
            return "learning_activities"
        if "learning activity" in text or name.startswith("prepare-"):
            return "learning_activity"
        if "assignment" in text or name.startswith("assignment-"):
            return "assignment"
        if "project" in text or name.startswith("project-"):
            return "project"
        if "setup" in text or name.startswith("setup-"):
            return "setup"
        if "final exam" in text:
            return "final_exam"
        if re.search(r"\bexam\b", text) or name.startswith("exam"):
            return "exam"
        if name.startswith("index."):
            if "course home" in text:
                return "course_home"
            if "course content" in text:
                return "course_content"
        return None

    @classmethod
    def _topic(cls, translated_heading, kind):
        topic = cls._clean_text(translated_heading)
        kind_prefix = cls._KIND_PREFIXES.get(kind)
        if kind == "audit" and kind_prefix:
            topic = re.sub(
                rf"^\s*[^\w]*(?:{kind_prefix})\s*(?:[-–—:]\s*)?",
                "",
                topic,
                flags=re.IGNORECASE,
            )
            topic = cls._LEADING_WEEK.sub("", topic)
        else:
            topic = cls._LEADING_WEEK.sub("", topic)
            if kind_prefix:
                topic = re.sub(
                    rf"^\s*(?:{kind_prefix})\s*(?:[-–—:]\s*)?",
                    "",
                    topic,
                    flags=re.IGNORECASE,
                )
        topic = topic.strip(" -–—:|")
        if kind in {"exam", "final_exam"} and topic.casefold() in {
            "exam", "final exam", "prova", "prova final",
        }:
            return ""
        if kind == "learning_activities" and topic.casefold() in {
            "learning activities", "atividades de aprendizagem",
        }:
            return ""
        return topic

    @classmethod
    def _canonical_title(cls, week, kind, topic):
        if kind == "course_home":
            return "Página Inicial do Curso"
        if kind == "course_content":
            return "Conteúdo do Curso"
        if week is None:
            return topic
        week_code = f"S{week:02d}"
        if kind == "week_index":
            return f"Semana {week:02d}" + (f" – {topic}" if topic else "")
        label = cls.KIND_LABELS.get(kind)
        if not label:
            return topic
        if kind == "audit":
            return f"{label}: {week_code}" + (f" – {topic}" if topic else "")
        if kind in {"learning_activities", "exam", "final_exam"} and not topic:
            return f"{week_code} – {label}"
        return f"{week_code} – {label}" + (f": {topic}" if topic else "")

    @classmethod
    def _heading_score(cls, text, kind, week):
        folded = cls._clean_text(text).casefold()
        score = 0
        if week is not None and (cls._WEEK_CODE.search(text) or cls._WEEK_NAME.search(text)):
            score += 4
        keywords = {
            "learning_activity": ("learning activity",),
            "learning_activities": ("learning activities",),
            "assignment": ("assignment",),
            "project": ("project",),
            "setup": ("setup",),
            "exam": ("exam",),
            "final_exam": ("final exam",),
            "audit": ("page audit",),
            "course_home": ("course home",),
        }.get(kind, ())
        if any(keyword in folded for keyword in keywords):
            score += 5
        if kind == "week_index" and cls._WEEK_NAME.search(text):
            score += 5
        if cls._COURSE_CODE.search(text) and not keywords:
            score -= 3
        return score

    @classmethod
    def _primary_heading_index(cls, headings, kind, week):
        if not headings:
            return None
        scores = [cls._heading_score(heading.get_text(" ", strip=True), kind, week) for heading in headings]
        best = max(range(len(headings)), key=lambda index: scores[index])
        if scores[best] > 0:
            return best
        for index, heading in enumerate(headings):
            text = heading.get_text(" ", strip=True)
            if heading.name == "h1" and not cls._COURSE_CODE.search(text):
                return index
        for index, heading in enumerate(headings):
            if heading.name == "h2":
                return index
        return 0

    @staticmethod
    def _replace_simple_text(element, value):
        text_nodes = [node for node in element.find_all(string=True) if str(node).strip()]
        if not text_nodes:
            element.append(value)
            return True
        text_nodes[0].replace_with(value)
        for node in text_nodes[1:]:
            node.replace_with("")
        return True

    @classmethod
    def _course_code(cls, soup):
        for element in [soup.find("h1"), soup.find("title")]:
            if element:
                match = cls._COURSE_CODE.search(element.get_text(" ", strip=True))
                if match:
                    return re.sub(r"\s+", " ", match.group(0))
        return ""

    @classmethod
    def _normalize_html(cls, source, translated, relative_path):
        source_soup = BeautifulSoup(source, "html.parser")
        translated_soup = BeautifulSoup(translated, "html.parser")
        source_headings = source_soup.find_all(["h1", "h2", "h3", "h4"])
        translated_headings = translated_soup.find_all(["h1", "h2", "h3", "h4"])
        source_text = " ".join(
            element.get_text(" ", strip=True)
            for element in ([source_soup.find("title")] + source_headings)
            if element
        )
        week = cls._week_number(source_text, relative_path)
        kind = cls._source_kind(source_text, relative_path)
        primary_index = cls._primary_heading_index(source_headings, kind, week) if kind else None

        for heading_index, (source_heading, translated_heading) in enumerate(
            zip(source_headings, translated_headings)
        ):
            source_heading_text = cls._clean_text(source_heading.get_text(" ", strip=True))
            fixed = cls.ENGLISH_TO_PORTUGUESE_HEADINGS.get(source_heading_text.casefold())
            if fixed:
                cls._replace_simple_text(translated_heading, fixed)
                continue
            heading_week = cls._week_number(source_heading_text, "")
            heading_kind = cls._source_kind(source_heading_text, "")
            if (
                heading_index != primary_index
                and heading_week is not None
                and heading_kind in cls.KIND_LABELS
            ):
                heading_topic = cls._topic(
                    translated_heading.get_text(" ", strip=True), heading_kind
                )
                cls._replace_simple_text(
                    translated_heading,
                    cls._canonical_title(heading_week, heading_kind, heading_topic),
                )

        canonical = ""
        topic = ""
        if kind:
            if primary_index is not None and primary_index < len(translated_headings):
                translated_heading = translated_headings[primary_index]
                topic = cls._topic(translated_heading.get_text(" ", strip=True), kind)
                canonical = cls._canonical_title(week, kind, topic)
                cls._replace_simple_text(translated_heading, canonical)

        html_tag = translated_soup.find("html")
        if html_tag:
            html_tag["lang"] = "pt-BR"

        title_tag = translated_soup.find("title")
        if title_tag and canonical:
            course_code = cls._course_code(source_soup)
            if kind == "week_index" and week is not None:
                page_title = f"Semana {week:02d} | Conteúdo do Curso"
            else:
                page_title = canonical
            title_tag.string = f"{course_code} | {page_title}" if course_code else page_title
        return str(translated_soup), {
            "kind": kind,
            "week": week,
            "canonical": canonical,
            "topic": topic,
        }

    @classmethod
    def _markdown_heading_matches(cls, content):
        return list(re.finditer(r"(?m)^(#{1,4})[ \t]+(.+?)[ \t]*#*[ \t]*$", content))

    @classmethod
    def _normalize_markdown(cls, source, translated, relative_path):
        source_matches = cls._markdown_heading_matches(source)
        translated_matches = cls._markdown_heading_matches(translated)
        source_text = " ".join(match.group(2) for match in source_matches)
        week = cls._week_number(source_text, relative_path)
        kind = cls._source_kind(source_text, relative_path)
        replacements = {}
        pseudo_headings = []
        for match in source_matches:
            level = len(match.group(1))
            pseudo = BeautifulSoup(
                f"<h{level}>{match.group(2)}</h{level}>", "html.parser"
            )
            pseudo_headings.append(pseudo.find())
        primary_index = (
            cls._primary_heading_index(pseudo_headings, kind, week)
            if kind else None
        )

        for index, source_match in enumerate(source_matches):
            if index >= len(translated_matches):
                break
            fixed = cls.ENGLISH_TO_PORTUGUESE_HEADINGS.get(
                cls._clean_text(source_match.group(2)).casefold()
            )
            if fixed:
                replacements[index] = fixed
                continue
            source_heading_text = cls._clean_text(source_match.group(2))
            heading_week = cls._week_number(source_heading_text, "")
            heading_kind = cls._source_kind(source_heading_text, "")
            if (
                index != primary_index
                and heading_week is not None
                and heading_kind in cls.KIND_LABELS
            ):
                heading_topic = cls._topic(
                    translated_matches[index].group(2), heading_kind
                )
                replacements[index] = cls._canonical_title(
                    heading_week, heading_kind, heading_topic
                )

        canonical = ""
        topic = ""
        if kind and source_matches and translated_matches:
            if primary_index is not None and primary_index < len(translated_matches):
                topic = cls._topic(translated_matches[primary_index].group(2), kind)
                canonical = cls._canonical_title(week, kind, topic)
                replacements[primary_index] = canonical

        if replacements:
            parts = []
            cursor = 0
            for index, match in enumerate(translated_matches):
                parts.append(translated[cursor:match.start()])
                if index in replacements:
                    parts.append(f"{match.group(1)} {replacements[index]}")
                else:
                    parts.append(match.group(0))
                cursor = match.end()
            parts.append(translated[cursor:])
            translated = "".join(parts)

        frontmatter_start = re.match(r"\A---[ \t]*\r?\n", translated)
        if canonical and frontmatter_start:
            frontmatter_end = re.search(
                r"(?m)^---[ \t]*$",
                translated[frontmatter_start.end():],
            )
            if frontmatter_end:
                boundary = frontmatter_start.end() + frontmatter_end.start()
                prefix = translated[:boundary]
                suffix = translated[boundary:]
                prefix = re.sub(
                    r"(?mi)^(title\s*:\s*).*$",
                    lambda match: f"{match.group(1)}{canonical}",
                    prefix,
                    count=1,
                )
                translated = prefix + suffix
        return translated, {
            "kind": kind,
            "week": week,
            "canonical": canonical,
            "topic": topic,
        }

    def normalize(self, source, translated, extension, relative_path):
        extension = extension.lower()
        if extension in {".html", ".htm"}:
            return self._normalize_html(source, translated, relative_path)[0]
        if extension in {".md", ".markdown", ".mdx"}:
            return self._normalize_markdown(source, translated, relative_path)[0]
        return translated

    @staticmethod
    def _resolved_content_target(current_path, href, records):
        parsed = urlparse(href)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return None
        raw = unquote(parsed.path).replace("\\", "/")
        if raw.startswith("/"):
            candidate = PurePosixPath(raw.lstrip("/"))
        else:
            candidate = PurePosixPath(current_path).parent / raw
        normalized = PurePosixPath(posixpath.normpath(str(candidate))).as_posix()
        candidates = [normalized]
        if not PurePosixPath(normalized).suffix:
            candidates.extend(
                f"{normalized.rstrip('/')}/{name}"
                for name in ("index.html", "index.htm", "index.md", "index.markdown", "index.mdx")
            )
            candidates.extend(f"{normalized}{suffix}" for suffix in (".html", ".md", ".mdx"))
        return next((candidate for candidate in candidates if candidate in records), None)

    def normalize_tree(self, source_root, translated_root, manifest):
        """Synchronize internal HTML link names with normalized target pages."""
        source_root = Path(source_root)
        translated_root = Path(translated_root)
        records = {}
        for item in manifest:
            if item.action != "translate" or item.extension not in {
                ".html", ".htm", ".md", ".markdown", ".mdx",
            }:
                continue
            source_path = source_root / item.relative_path
            translated_path = translated_root / item.relative_path
            if not translated_path.is_file():
                continue
            source = source_path.read_text(encoding="utf-8")
            translated = translated_path.read_text(encoding="utf-8")
            if item.extension in {".html", ".htm"}:
                source_soup = BeautifulSoup(source, "html.parser")
                source_headings = source_soup.find_all(["h1", "h2", "h3", "h4"])
                source_text = " ".join(
                    element.get_text(" ", strip=True) for element in source_headings
                )
                week = self._week_number(source_text, item.relative_path)
                kind = self._source_kind(source_text, item.relative_path)
                normalized, data = self._normalize_html(
                    source, translated, item.relative_path
                )
                primary_index = (
                    self._primary_heading_index(source_headings, kind, week)
                    if kind else None
                )
                source_heading = (
                    source_headings[primary_index].get_text(" ", strip=True)
                    if primary_index is not None and primary_index < len(source_headings)
                    else ""
                )
            else:
                source_matches = self._markdown_heading_matches(source)
                source_text = " ".join(match.group(2) for match in source_matches)
                week = self._week_number(source_text, item.relative_path)
                kind = self._source_kind(source_text, item.relative_path)
                normalized, data = self._normalize_markdown(
                    source, translated, item.relative_path
                )
                pseudo_headings = []
                for match in source_matches:
                    level = len(match.group(1))
                    pseudo = BeautifulSoup(
                        f"<h{level}>{match.group(2)}</h{level}>", "html.parser"
                    )
                    pseudo_headings.append(pseudo.find())
                primary_index = (
                    self._primary_heading_index(pseudo_headings, kind, week)
                    if kind else None
                )
                source_heading = (
                    source_matches[primary_index].group(2)
                    if primary_index is not None and primary_index < len(source_matches)
                    else ""
                )
            translated_path.write_text(normalized, encoding="utf-8", newline="")
            records[item.relative_path] = {
                "source_heading": self._clean_text(source_heading),
                "source_topic": self._topic(source_heading, kind) if kind else "",
                **data,
            }

        changed = []
        for item in manifest:
            if item.relative_path not in records:
                continue
            source_path = source_root / item.relative_path
            translated_path = translated_root / item.relative_path
            if item.extension in {".md", ".markdown", ".mdx"}:
                source = source_path.read_text(encoding="utf-8")
                translated = translated_path.read_text(encoding="utf-8")
                link_pattern = re.compile(
                    r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)"
                )
                source_links = list(link_pattern.finditer(source))
                translated_links = list(link_pattern.finditer(translated))
                replacements = []
                for source_link, translated_link in zip(source_links, translated_links):
                    target = self._resolved_content_target(
                        item.relative_path, source_link.group(2), records
                    )
                    record = records.get(target or "")
                    if not record:
                        continue
                    source_label = self._clean_text(source_link.group(1))
                    replacement = ""
                    if (
                        source_label.casefold() == record["source_topic"].casefold()
                        and record["topic"]
                    ):
                        replacement = record["topic"]
                    elif (
                        source_label.casefold() == record["source_heading"].casefold()
                        and record["canonical"]
                    ):
                        replacement = record["canonical"]
                    if replacement:
                        replacements.append(
                            (translated_link.start(1), translated_link.end(1), replacement)
                        )
                if replacements:
                    for start, end, replacement in reversed(replacements):
                        translated = translated[:start] + replacement + translated[end:]
                    translated_path.write_text(translated, encoding="utf-8", newline="")
                    changed.append(item.relative_path)
                continue

            source_soup = BeautifulSoup(source_path.read_text(encoding="utf-8"), "html.parser")
            translated_soup = BeautifulSoup(translated_path.read_text(encoding="utf-8"), "html.parser")
            modified = False
            for source_link, translated_link in zip(
                source_soup.find_all("a", href=True),
                translated_soup.find_all("a", href=True),
            ):
                if translated_link.find(True) is not None:
                    continue
                target = self._resolved_content_target(
                    item.relative_path, source_link.get("href", ""), records
                )
                record = records.get(target or "")
                if not record:
                    continue
                source_label = self._clean_text(source_link.get_text(" ", strip=True))
                if source_label.casefold() == record["source_topic"].casefold() and record["topic"]:
                    translated_link.string = record["topic"]
                    modified = True
                elif source_label.casefold() == record["source_heading"].casefold() and record["canonical"]:
                    translated_link.string = record["canonical"]
                    modified = True
            if modified:
                translated_path.write_text(str(translated_soup), encoding="utf-8", newline="")
                changed.append(item.relative_path)
        return changed
