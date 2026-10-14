import json
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from bots.api_settings_analysis import APISettingsAnalysisBot


class _Response:
    def __init__(self, text):
        self.text = text


class _SettingsModel:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def generate_content(self, prompt, request_options=None):
        self.prompts.append(prompt)
        return _Response(json.dumps(self.payload))


class APISettingsAnalysisBotTests(unittest.TestCase):
    def test_extracts_render_configuration_from_course_page(self):
        model = _SettingsModel({
            "api_settings": [
                {
                    "provider": "Render",
                    "setting": "Build Command",
                    "value": "npm install && npm run build",
                    "context_summary_pt": "Comando usado para construir o site.",
                },
                {
                    "provider": "Render",
                    "setting": "Publish Directory",
                    "value": "dist",
                    "context_summary_pt": "Diretório publicado pelo serviço.",
                },
            ]
        })
        source = (
            "<h1>Publishing</h1><p>Create a Static Site on Render.com.</p>"
            "<p>Build Command: <code>npm install &amp;&amp; npm run build</code></p>"
            "<p>Publish Directory: <code>dist</code></p>"
        )

        rows = APISettingsAnalysisBot(model=model).analyze(
            source, ".html", "Team Activity", "week01/team.html"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["provider"], "Render")
        self.assertEqual(rows[0]["setting"], "Build Command")
        self.assertEqual(rows[1]["value"], "dist")
        self.assertIn("Render deployment settings count", model.prompts[0])
        self.assertIn("NEVER return an actual password", model.prompts[0])

    def test_skips_pages_without_configuration_indicators(self):
        model = _SettingsModel({"api_settings": []})
        rows = APISettingsAnalysisBot(model=model).analyze(
            "<h1>Welcome</h1><p>Read the lesson and discuss it.</p>",
            ".html",
            "Welcome",
            "index.html",
        )
        self.assertEqual(rows, [])
        self.assertEqual(model.prompts, [])

    def test_redacts_secrets_before_model_submission_and_reporting(self):
        secret = "ghp_1234567890abcdefghijklmnop"
        model = _SettingsModel({
            "api_settings": [{
                "provider": "GitHub",
                "setting": "API token",
                "value": secret,
                "context_summary_pt": f"Use o token {secret} no painel.",
            }]
        })

        rows = APISettingsAnalysisBot(model=model).analyze(
            f"Set API_TOKEN={secret} in the environment.",
            ".md",
            "Deployment",
            "deploy.md",
        )

        self.assertNotIn(secret, model.prompts[0])
        self.assertEqual(rows[0]["value"], "[REDACTED]")
        self.assertNotIn(secret, rows[0]["context_summary"])
        self.assertIn("[REDACTED]", rows[0]["context_summary"])

    def test_redacts_natural_language_password_assignments(self):
        redacted = APISettingsAnalysisBot._redact_secrets(
            "The deployment password is correct-horse-battery-staple."
        )
        self.assertNotIn("correct-horse-battery-staple", redacted)
        self.assertIn("password is [REDACTED]", redacted)
