"""CLI wrapper for credential-safe Canvas Classic Question Bank renaming."""

import argparse
import json
import os
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.canvas_question_bank_renamer import (  # noqa: E402
    APPROVAL_PHRASE,
    CanvasQuestionBankRenamer,
)


def login_checkpoint(payload):
    print(payload["details"])
    print(f"Browser page: {payload['url']}")
    answer = input("Press Enter after login is complete, or type CANCEL: ").strip()
    return answer.casefold() != "cancel"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Dry-run or apply Translation IDs to Canvas Classic Question Bank names."
    )
    parser.add_argument("registry", help="Path to the canonical Translation ID registry JSON")
    parser.add_argument("course_url", help="Exact Canvas course URL ending in /courses/<id>")
    parser.add_argument("--language", choices=("EN", "PTBR", "SPA", "FRA"), required=True)
    parser.add_argument(
        "--mode",
        choices=("source-register", "target-reconcile"),
        required=True,
    )
    parser.add_argument("--apply", action="store_true", help="Apply the approved rename plan")
    parser.add_argument(
        "--approval-phrase",
        default="",
        help=f"Required with --apply; exact value: {APPROVAL_PHRASE}",
    )
    parser.add_argument("--plan", help="Use a previously reviewed dry-run plan JSON")
    args = parser.parse_args(argv)

    service = CanvasQuestionBankRenamer(
        args.registry,
        args.course_url,
        args.language,
        args.mode,
    )
    if args.plan:
        with open(args.plan, "r", encoding="utf-8") as plan_file:
            plan = json.load(plan_file)
    else:
        live_banks = service.discover(login_checkpoint)
        plan = service.plan(live_banks)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0
    live_writes_enabled = os.getenv(
        "TRANSLATION_ID_LIVE_WRITES_ENABLED", ""
    ).strip().casefold() in {"1", "true", "yes", "on"}
    if not live_writes_enabled:
        parser.error(
            "Live writes are disabled pending disposable-course staging verification. "
            "Set TRANSLATION_ID_LIVE_WRITES_ENABLED=true only for the controlled "
            "staging run or after production rollout approval."
        )
    result = service.apply(plan, args.approval_phrase, login_checkpoint)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

