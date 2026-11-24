import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.canvas_question_bank_renamer import (  # noqa: E402
    CANVAS_ACCOUNT_BOOTSTRAP_URL,
    CANVAS_LOGIN_URL,
    CANVAS_LOGIN_SUCCESS_URL,
    CanvasQuestionBankError,
    CanvasQuestionBankRenamer,
    format_question_bank_name,
)
from core.translation_id_registry import (  # noqa: E402
    LANGUAGES,
    TranslationIdRegistry,
    empty_language_instance,
)


def bank_item(translation_id, title, stable_key):
    instances = {language: empty_language_instance(language) for language in LANGUAGES}
    instances["EN"]["title"] = title
    return {
        "translation_id": translation_id,
        "short_id": translation_id.split("-", 1)[1],
        "item_type": "Question Bank",
        "source_title": title,
        "stable_key": stable_key,
        "package_paths": [f"non_cc_assessments/{stable_key}.xml.qti"],
        "placement": "question_bank_title",
        "retired": False,
        "instances": instances,
    }


class CanvasQuestionBankRenamerTests(unittest.TestCase):
    def setUp(self):
        self.registry = TranslationIdRegistry(
            "GS170",
            "123",
            [
                bank_item("GS170-QB-001", "QB: GS 170 W01 Questions", "bank-1"),
                bank_item("GS170-QB-002", "Unfiled Questions", "bank-2"),
            ],
        )
        self.service = CanvasQuestionBankRenamer(
            self.registry,
            "https://canvas.test/courses/123",
            "EN",
            "source-register",
            profile_dir=Path.home() / "WWOTranslationHUB-test-profile",
        )

    def test_plan_proposes_exact_names_and_reports_noneditable_unfiled(self):
        plan = self.service.plan([
            {
                "id": 10,
                "name": "QB: GS 170 W01 Questions",
                "url": "https://canvas.test/courses/123/question_banks/10",
                "editable": True,
            },
            {
                "id": 11,
                "name": "Unfiled Questions",
                "url": "https://canvas.test/courses/123/question_banks/11",
                "editable": False,
            },
        ])
        by_id = {change["translation_id"]: change for change in plan["changes"]}
        self.assertEqual(by_id["GS170-QB-001"]["status"], "Rename")
        self.assertEqual(
            by_id["GS170-QB-001"]["new_name"],
            "QB: GS 170 W01 Questions TranslationID: GS170-QB-001",
        )
        self.assertEqual(by_id["GS170-QB-002"]["status"], "Non-editable")
        self.assertIn("Unfiled Questions", by_id["GS170-QB-002"]["detail"])

    def test_plan_is_idempotent_and_detects_different_marker(self):
        correct = self.service.plan([
            {
                "id": 10,
                "name": "QB: GS 170 W01 Questions TranslationID: GS170-QB-001",
                "editable": True,
            },
            {"id": 11, "name": "Unfiled Questions", "editable": False},
        ])
        self.assertEqual(correct["changes"][0]["status"], "Correct")
        self.assertEqual(
            self.registry.items[0]["instances"]["EN"]["id_status"],
            "correct",
        )
        self.assertEqual(
            self.registry.items[0]["instances"]["EN"]["content_id"],
            "10",
        )

        conflict = self.service.plan([
            {
                "id": 10,
                "name": "QB: GS 170 W01 Questions TranslationID: GS170-QB-999",
                "editable": True,
            },
            {"id": 11, "name": "Unfiled Questions", "editable": False},
        ])
        self.assertEqual(conflict["changes"][0]["status"], "Conflict")

    def test_plan_reports_missing_duplicate_and_extra_banks(self):
        plan = self.service.plan([
            {"id": 10, "name": "QB: GS 170 W01 Questions", "editable": True},
            {"id": 12, "name": "QB: GS 170 W01 Questions", "editable": True},
            {"id": 99, "name": "Unexpected Bank", "editable": True},
        ])
        by_id = {change["translation_id"]: change for change in plan["changes"]}
        self.assertEqual(by_id["GS170-QB-001"]["status"], "Duplicate")
        self.assertEqual(by_id["GS170-QB-002"]["status"], "Missing")
        self.assertEqual(len(plan["extra_banks"]), 3)
        with self.assertRaisesRegex(CanvasQuestionBankError, "extra-bank"):
            self.service.validate_plan_for_apply(plan)

    def test_helper_is_idempotent_and_fails_closed(self):
        expected = "QB: GS 170 W01 Questions TranslationID: GS170-QB-001"
        self.assertEqual(
            format_question_bank_name("QB: GS 170 W01 Questions", "GS170-QB-001"),
            expected,
        )
        self.assertEqual(format_question_bank_name(expected, "GS170-QB-001"), expected)
        with self.assertRaises(CanvasQuestionBankError):
            format_question_bank_name(
                "QB: GS 170 W01 Questions TranslationID: GS170-QB-002",
                "GS170-QB-001",
            )

    def test_source_course_and_profile_safety_are_enforced(self):
        with self.assertRaisesRegex(CanvasQuestionBankError, "source course"):
            CanvasQuestionBankRenamer(
                self.registry,
                "https://canvas.test/courses/999",
                "EN",
                "source-register",
                profile_dir=Path.home() / "profile",
            )
        unsafe = CanvasQuestionBankRenamer(
            self.registry,
            "https://canvas.test/courses/123",
            "EN",
            "source-register",
            profile_dir=Path(__file__).resolve().parents[1] / "profile",
        )
        with self.assertRaisesRegex(CanvasQuestionBankError, "outside the repository"):
            unsafe._ensure_profile_is_outside_repository()

    def test_browser_uses_required_login_account_and_question_bank_order(self):
        class FakePage:
            def __init__(self):
                self.gotos = []
                self.waits = []
                self.url = ""
                self.live_url = ""

            def goto(self, url, wait_until=None):
                self.gotos.append((url, wait_until))
                self.url = url
                self.live_url = url

            def evaluate(self, script):
                self.asserted_script = script
                return self.live_url

            def wait_for_load_state(self, state):
                self.waits.append(state)

        page = FakePage()
        checkpoints = []

        def complete_login(payload):
            checkpoints.append(payload)
            # Reproduce the real bug: Playwright's cached page.url remains on
            # the login page while the browser's window.location has advanced.
            page.live_url = CANVAS_LOGIN_SUCCESS_URL
            return True

        manage_url = self.service._open_question_banks_after_login(
            page,
            complete_login,
        )

        self.assertEqual(
            [url for url, _wait in page.gotos],
            [
                CANVAS_LOGIN_URL,
                CANVAS_ACCOUNT_BOOTSTRAP_URL,
                "https://canvas.test/courses/123/question_banks",
            ],
        )
        self.assertEqual(manage_url, page.gotos[-1][0])
        self.assertEqual(page.asserted_script, "window.location.href")
        self.assertEqual(page.waits, ["networkidle"])
        self.assertEqual(checkpoints[0]["url"], CANVAS_LOGIN_URL)
        self.assertEqual(
            checkpoints[0]["success_url"],
            CANVAS_LOGIN_SUCCESS_URL,
        )
        self.assertEqual(
            checkpoints[0]["next_url"],
            CANVAS_ACCOUNT_BOOTSTRAP_URL,
        )

    def test_cancelled_login_does_not_open_account_or_course(self):
        class FakePage:
            def __init__(self):
                self.gotos = []

            def goto(self, url, wait_until=None):
                self.gotos.append(url)

        page = FakePage()
        with self.assertRaisesRegex(CanvasQuestionBankError, "cancelled"):
            self.service._open_question_banks_after_login(
                page,
                lambda _payload: False,
            )
        self.assertEqual(page.gotos, [CANVAS_LOGIN_URL])

    def test_unverified_login_reprompts_without_closing_browser(self):
        class FakePage:
            def __init__(self):
                self.gotos = []
                self.url = ""
                self.live_url = ""

            def goto(self, url, wait_until=None):
                self.gotos.append(url)
                self.url = url
                self.live_url = url

            def evaluate(self, _script):
                return self.live_url

            def wait_for_load_state(self, _state):
                pass

        page = FakePage()
        checkpoints = []

        def complete_on_second_prompt(payload):
            checkpoints.append(payload)
            if len(checkpoints) == 2:
                page.live_url = CANVAS_LOGIN_SUCCESS_URL
            return True

        self.service._open_question_banks_after_login(
            page,
            complete_on_second_prompt,
        )

        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[0]["attempt"], 1)
        self.assertEqual(checkpoints[1]["attempt"], 2)
        self.assertIn("not verified", checkpoints[1]["details"])
        self.assertEqual(
            page.gotos,
            [
                CANVAS_LOGIN_URL,
                CANVAS_ACCOUNT_BOOTSTRAP_URL,
                "https://canvas.test/courses/123/question_banks",
            ],
        )

    def test_rename_one_in_page_flow(self):
        class FakeLocator:
            def __init__(self, elements=None, count_val=1):
                self._elements = elements or {}
                self._count = count_val

            def count(self):
                return self._count

            @property
            def first(self):
                return self

            def locator(self, selector):
                if ".edit_bank_link" in selector:
                    return FakeLocator(count_val=1)
                if "#edit_bank_form" in selector or "form" in selector:
                    return FakeLocator(count_val=1)
                if 'input' in selector:
                    return FakeLocator(count_val=1)
                if "submit" in selector:
                    return FakeLocator(count_val=1)
                if "a.title" in selector:
                    return FakeLocator(count_val=1, elements={"text": "QB New Name TranslationID: GS170-QB-001"})
                return FakeLocator(count_val=0)

            def click(self):
                pass

            def fill(self, val):
                self.filled_val = val

            def press(self, key):
                self.pressed_key = key

            def is_visible(self):
                return True

            def wait_for(self, **kwargs):
                pass

            def inner_text(self):
                return self._elements.get("text", "")

            def text_content(self):
                return self._elements.get("text", "")

        class FakePage:
            def __init__(self):
                self.live_url = "https://canvas.test/courses/123/question_banks"
                self.reloaded = False

            def locator(self, selector):
                if "#question_bank_10" in selector:
                    return FakeLocator(count_val=1)
                if "#edit_bank_form" in selector:
                    return FakeLocator(count_val=1)
                return FakeLocator(count_val=0)

            def evaluate(self, _script):
                return self.live_url

            def wait_for_load_state(self, _state):
                pass

            def wait_for_timeout(self, _ms):
                pass

            def reload(self, **kwargs):
                self.reloaded = True

        page = FakePage()
        change = {
            "translation_id": "GS170-QB-001",
            "live_id": "10",
            "old_name": "QB: GS 170 W01 Questions",
            "new_name": "QB New Name TranslationID: GS170-QB-001",
        }
        self.service._rename_one(page, change)


if __name__ == "__main__":
    unittest.main()

