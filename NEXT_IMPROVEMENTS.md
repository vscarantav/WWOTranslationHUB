# TranslationHUB — Next Improvements

This is the single source of truth for planned improvements that are not yet complete. Agents must read this file at the start of every task, remind the user about unchecked items, and update it when work is completed or new follow-up work is discovered.

## Backlog

- [ ] Extend `ScriptureCheckBot` to recognize and resolve Bible references.
- [ ] Implement and approve Microsoft Word (`.docx`) translation and repackaging.
- [ ] Implement and approve Microsoft PowerPoint (`.pptx`) translation and repackaging.
- [ ] Implement localized image-file translation for JPG, PNG, GIF, and SVG assets; inline alt-text translation already exists.
- [ ] Preserve every question bank's English name exactly as it appears in the original export package.
- [ ] Add an interactive recovery flow when an XML/QTI file still fails after three translation attempts (for example, `Unable to translate XML batch after 3 attempts`). Do not terminate the translation run or immediately abandon IMSCC creation. Show the failed file and error, prompt the user to translate or correct that file manually, and then offer an option to validate the corrected file and continue the remaining translation and packaging workflow.

## Needs user details before implementation

- [ ] Update the special Setup Notes page flow so specified parts of its text remain dark red.
  - Do not implement until the user identifies the exact text segments and provides the required color/style rules.
- [ ] Add a special flow for the `W07 End of Course Evaluation` assignment: fetch the approved Portuguese version from the PT template through the Canvas API instead of translating the English assignment. Every course should receive the template version; when the assignment exists in the English package, ignore that source file and replace it with the fetched version.
  - Do not implement until the user provides the PT template details, assignment identification rules, and any required Canvas API/import information.

## Watch conditions

- If bots begin using different Gemini API keys or projects, add an actionable backlog item to replace global `genai.configure()` state with per-bot client instances before enabling concurrent calls. This is not currently actionable while all bots share one key.

## Maintenance rules

- Use `[ ]` for open work and `[x]` only after the change has been implemented and verified.
- Keep entries short, actionable, and free of implementation details that belong in `app/App_Architecture.json` or a dedicated design document.
- Add a brief indented completion note with the verification date when closing an item.
- Do not delete completed items; move them to a `Completed` section so the project keeps a lightweight history.
