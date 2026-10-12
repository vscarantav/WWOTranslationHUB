import shutil
import sys
import unittest
import uuid
from pathlib import Path

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.github_naming_normalizer import GitHubNamingNormalizer
from core.github_repository_scanner import RepositoryFile


class GitHubNamingNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = GitHubNamingNormalizer()

    def test_normalizes_imperfect_html_activity_title_and_standard_sections(self):
        source = (
            '<html lang="en"><head><title>CSE 340 | Routing</title></head><body>'
            '<h1>CSE 340: Web Backend Development</h1>'
            '<h2>Week 2 Learning Activity - Routing</h2>'
            '<h3>Overview</h3><h3>Testing</h3>'
            '<script>const label = "W02";</script></body></html>'
        )
        translated = (
            '<html lang="en"><head><title>CSE 340 | Roteamento</title></head><body>'
            '<h1>CSE 340: Desenvolvimento de Back-end Web</h1>'
            '<h2>Semana 2 — Atividade de Aprendizagem - Roteamento</h2>'
            '<h3>Resumo</h3><h3>Teste</h3>'
            '<script>const label = "W02";</script></body></html>'
        )

        result = self.normalizer.normalize(
            source, translated, ".html", "week02/prepare-routing.html"
        )
        soup = BeautifulSoup(result, "html.parser")

        self.assertEqual(soup.html["lang"], "pt-BR")
        self.assertEqual(soup.title.get_text(), "CSE 340 | S02 – Atividade de Aprendizagem: Roteamento")
        self.assertEqual(soup.h2.get_text(), "S02 – Atividade de Aprendizagem: Roteamento")
        self.assertEqual([tag.get_text() for tag in soup.find_all("h3")], ["Visão Geral", "Testes"])
        self.assertIn('"W02"', soup.script.get_text())

    def test_infers_assignment_from_path_when_source_heading_has_no_prefix(self):
        result = self.normalizer.normalize(
            "<html><body><h1>Picture Album</h1></body></html>",
            "<html><body><h1>Álbum de Imagens</h1></body></html>",
            ".html",
            "week02/assignment-02.html",
        )

        self.assertEqual(
            BeautifulSoup(result, "html.parser").h1.get_text(),
            "S02 – Tarefa: Álbum de Imagens",
        )

    def test_preserves_inline_heading_elements_while_normalizing_visible_title(self):
        result = self.normalizer.normalize(
            '<html><body><h1>CSE 340</h1><h2>W03 Assignment: <span>Country Page</span></h2></body></html>',
            '<html><body><h1>CSE 340</h1><h2>S3 — Tarefa: <span>Página do País</span></h2></body></html>',
            ".html",
            "week03/assignment-03.html",
        )
        soup = BeautifulSoup(result, "html.parser")

        self.assertIsNotNone(soup.h2.span)
        self.assertEqual(soup.h2.get_text(" ", strip=True), "S03 – Tarefa: Página do País")

    def test_normalizes_week_index_title_and_group_headings(self):
        source = (
            '<html><head><title>WDD 131 | Week 01 | Course Content</title></head><body>'
            '<h1>WDD 131: Dynamic Web Fundamentals</h1>'
            '<h2>Week 01 - Setup and Introduction</h2>'
            '<h3>W01 Learning Activities</h3>'
            '<h3>W01 Assignment: Home Page</h3></body></html>'
        )
        translated = (
            '<html><head><title>WDD 131 | Semana 1</title></head><body>'
            '<h1>WDD 131: Fundamentos da Web Dinâmica</h1>'
            '<h2>Semana 1 — Configuração e Introdução</h2>'
            '<h3>S1 - Atividades de Aprendizagem</h3>'
            '<h3>S1 — Tarefa - Página Inicial</h3></body></html>'
        )

        result = self.normalizer.normalize(source, translated, ".html", "week01/index.html")
        soup = BeautifulSoup(result, "html.parser")

        self.assertEqual(soup.title.get_text(), "WDD 131 | Semana 01 | Conteúdo do Curso")
        self.assertEqual(soup.h2.get_text(), "Semana 01 – Configuração e Introdução")
        self.assertEqual(
            [tag.get_text() for tag in soup.find_all("h3")],
            ["S01 – Atividades de Aprendizagem", "S01 – Tarefa: Página Inicial"],
        )

    def test_uses_glossary_course_home_name_on_root_index(self):
        source = (
            '<html lang="en"><head><title>CSE 340 | Course Content Main Menu</title></head>'
            '<body><h1>CSE 340: Web Backend Development</h1><h2>Course Home</h2></body></html>'
        )
        translated = (
            '<html lang="en"><head><title>CSE 340 | Conteúdo</title></head>'
            '<body><h1>CSE 340: Desenvolvimento de Back-end Web</h1><h2>Início</h2></body></html>'
        )

        result = self.normalizer.normalize(source, translated, ".html", "index.html")
        soup = BeautifulSoup(result, "html.parser")

        self.assertEqual(soup.h2.get_text(), "Página Inicial do Curso")
        self.assertEqual(soup.title.get_text(), "CSE 340 | Página Inicial do Curso")

    def test_normalizes_audit_title_with_leading_icon(self):
        source = (
            '<html><head><title>WDD 131 | Page Audit</title></head><body>'
            '<h1>WDD 131</h1><h2>✔ Page Audit: W03 - Country Page</h2></body></html>'
        )
        translated = (
            '<html><head><title>WDD 131 | Auditoria</title></head><body>'
            '<h1>WDD 131</h1><h2>☑️ Auditoria de Páginas: S3 — Página do País</h2></body></html>'
        )

        result = self.normalizer.normalize(
            source, translated, ".html", "audit/w03-country.html"
        )
        soup = BeautifulSoup(result, "html.parser")

        self.assertEqual(soup.h2.get_text(), "Auditoria de Páginas: S03 – Página do País")

    def test_normalizes_markdown_heading_and_existing_frontmatter_title(self):
        source = (
            "---\ntitle: Picture Album\nlayout: lesson\n---\n\n"
            "# Picture Album\n\n## Overview\n"
        )
        translated = (
            "---\ntitle: Picture Album\nlayout: lesson\n---\n\n"
            "# Álbum de Imagens\n\n## Resumo\n"
        )

        result = self.normalizer.normalize(
            source, translated, ".md", "week02/assignment-02.md"
        )

        self.assertIn("title: S02 – Tarefa: Álbum de Imagens", result)
        self.assertIn("# S02 – Tarefa: Álbum de Imagens", result)
        self.assertIn("## Visão Geral", result)
        self.assertIn("layout: lesson", result)

    def test_synchronizes_week_index_link_with_target_page_topic(self):
        root = Path.cwd() / "tests" / f"_naming_{uuid.uuid4().hex}"
        source_root = root / "source"
        translated_root = root / "translated"
        try:
            (source_root / "week02").mkdir(parents=True)
            (translated_root / "week02").mkdir(parents=True)
            (source_root / "week02" / "index.html").write_text(
                '<h1>CSE 340</h1><h2>Week 02 - Routing</h2>'
                '<a href="assignment-02.html">Picture Album</a>',
                encoding="utf-8",
            )
            (translated_root / "week02" / "index.html").write_text(
                '<h1>CSE 340</h1><h2>Semana 2 - Roteamento</h2>'
                '<a href="assignment-02.html">Álbum ilustrado</a>',
                encoding="utf-8",
            )
            (source_root / "week02" / "assignment-02.html").write_text(
                '<h1>CSE 340</h1><h2>W02 Assignment: Picture Album</h2>',
                encoding="utf-8",
            )
            (translated_root / "week02" / "assignment-02.html").write_text(
                '<h1>CSE 340</h1><h2>S2 — Tarefa - Álbum de Imagens</h2>',
                encoding="utf-8",
            )
            manifest = [
                RepositoryFile("week02/index.html", ".html", "translate", "HTML", 1),
                RepositoryFile("week02/assignment-02.html", ".html", "translate", "HTML", 1),
            ]

            changed = self.normalizer.normalize_tree(source_root, translated_root, manifest)
            output = BeautifulSoup(
                (translated_root / "week02" / "index.html").read_text(encoding="utf-8"),
                "html.parser",
            )

            self.assertEqual(changed, ["week02/index.html"])
            self.assertEqual(output.a.get_text(), "Álbum de Imagens")
            self.assertEqual(output.h2.get_text(), "Semana 02 – Roteamento")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_synchronizes_markdown_link_with_target_page_topic(self):
        root = Path.cwd() / "tests" / f"_naming_md_{uuid.uuid4().hex}"
        source_root = root / "source"
        translated_root = root / "translated"
        try:
            (source_root / "week02").mkdir(parents=True)
            (translated_root / "week02").mkdir(parents=True)
            (source_root / "week02" / "index.md").write_text(
                "# Week 02 - Routing\n\n[Picture Album](assignment-02.md)\n",
                encoding="utf-8",
            )
            (translated_root / "week02" / "index.md").write_text(
                "# Semana 2 - Roteamento\n\n[Álbum ilustrado](assignment-02.md)\n",
                encoding="utf-8",
            )
            (source_root / "week02" / "assignment-02.md").write_text(
                "# W02 Assignment: Picture Album\n",
                encoding="utf-8",
            )
            (translated_root / "week02" / "assignment-02.md").write_text(
                "# S2 — Tarefa - Álbum de Imagens\n",
                encoding="utf-8",
            )
            manifest = [
                RepositoryFile("week02/index.md", ".md", "translate", "Markdown", 1),
                RepositoryFile("week02/assignment-02.md", ".md", "translate", "Markdown", 1),
            ]

            changed = self.normalizer.normalize_tree(source_root, translated_root, manifest)
            output = (translated_root / "week02" / "index.md").read_text(encoding="utf-8")

            self.assertEqual(changed, ["week02/index.md"])
            self.assertIn("[Álbum de Imagens](assignment-02.md)", output)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
