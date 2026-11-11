# TranslationHUB Agent Instructions

These instructions apply to every agent working anywhere in this repository.

## Required improvements check

1. Before planning or changing anything, read `NEXT_IMPROVEMENTS.md`.
2. In the first progress update, remind the user about every unchecked improvement. Keep the reminder concise and separate from the active task.
3. Do not treat an unchecked improvement as part of the active task unless the user asks for it or it is required to complete the requested work safely.
4. When the active task completes an improvement, change its checkbox to `[x]` and add a short completion note. Do not mark it complete without verification.
5. Add newly discovered follow-up work to `NEXT_IMPROVEMENTS.md` when it is useful but outside the current task's scope. Avoid duplicate entries.
6. In the final response, include an `Outstanding improvements` reminder whenever unchecked items remain. If none remain, say that the improvements list is clear.

`NEXT_IMPROVEMENTS.md` is the single source of truth for the project's future-work backlog. Detailed architecture and current implementation contracts remain in `app/App_Architecture.json`.

## Commit classification

Every commit created by an agent must identify exactly one primary category at the start of its subject:

- `fix:` corrects defective behavior, a regression, or an incorrect result.
- `maintenance:` covers documentation, refactoring, tests, dependencies, configuration, cleanup, and generated-artifact maintenance without adding an intended user-facing capability.
- `improvement:` adds a capability or materially enhances existing behavior.

Use the format `<category>: <imperative summary>`. When a commit contains mixed work, choose the category that represents its primary purpose and describe secondary work in the commit body.
