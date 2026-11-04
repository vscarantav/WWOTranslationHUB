# TranslationHUB — Next Improvements

This is the single source of truth for planned improvements that are not yet complete. Agents must read this file at the start of every task, remind the user about unchecked items, and update it when work is completed or new follow-up work is discovered.

## Backlog

- [ ] Extend `ScriptureCheckBot` to recognize and resolve Bible references.
- [ ] Implement and approve Microsoft PowerPoint (`.pptx`) translation and repackaging.
- [ ] Implement localized image-file translation for JPG, PNG, GIF, and SVG assets; inline alt-text translation already exists.
- [ ] Preserve every question bank's English name exactly as it appears in the original export package.
- [ ] Migrate the translation bots from the deprecated `google.generativeai` SDK to `google.genai`, preserving and verifying the existing retry, validation, and successful-call tracking behavior.
- [ ] Add a `Continue Previous Process` button that saves durable progress checkpoints during long-running workflows and safely resumes the most recent incomplete process from its last verified stopping point after the user leaves or closes the HUB.
- [ ] Add a safe multi-computer auto-update flow controlled by the public master Git repository. Provide an `Update Translation HUB` interface button (no separate batch file) that pulls `main`, shows update status in the HUB, and automatically restarts the application after a successful update. Send newly added links to the shared mapping database immediately after the user completes the link-mapping flow. When one English link has conflicting Portuguese links, show every candidate in that flow with a copy button and single-select checkbox, require exactly one selection, and permanently save the selected link as the correct mapping without losing unrelated mappings.

## Needs user details before implementation

- [ ] Update the special Setup Notes page flow so specified parts of its text remain dark red.
  - Do not implement until the user identifies the exact text segments and provides the required color/style rules.
- [ ] Implement the requested changes to Sergio's flow and merge the two report models into one standardized report that matches the shared process used for everyone.
  - Before implementation, confirm the required Sergio-flow changes, identify the two report models to merge, and document the expected shared report structure and workflow.

## Completed

- [x] Update the production EdTech extraction and injection flow for the current books.byui.edu TOC and editor controls.
  - Completed 2026-11-04: The Translation Hub now fetches through the live TOC, visible Edit link, HTML role button, and complete CodeMirror clipboard source; repopulation uses the current title, Save, and Close controls, refreshes stale chapter slugs with title validation, and reopens every saved page for persisted HTML/title verification. It also opens the optional current subtitle accordion during extraction, repopulation, and verification. The established Google login flow was left unchanged. Verified with 30 focused EdTech tests, the full repository suite, and the same selector sequence that completed the live 28/28 BUS115-PT recovery.

- [x] Exempt legitimate source-language bibliography citations from unchanged-English failure detection so an untranslated publication title does not fail an otherwise valid HTML translation.
  - Completed 2026-11-04: Explicitly marked bibliography/reference nodes are preserved outside HTML translation batches, while unchanged-English validation remains active for instructional content. Verified with focused bot tests, successful regeneration of the previously failed BUS115-PT Chapter 1 translation, and live save/reopen verification during the 28-page EdTech recovery.

- [x] Add an interactive recovery flow when an XML/QTI file still fails after three translation attempts (for example, `Unable to translate XML batch after 3 attempts`). Do not terminate the translation run or immediately abandon IMSCC creation. Show the failed file and error, prompt the user to translate or correct that file manually, and then offer an option to validate the corrected file and continue the remaining translation and packaging workflow.
  - Completed 2026-11-02: Isolated XML/QTI failures from hard aborts during translation retries; failed XML/QTI files retain the English source placeholder, allow IMSCC repackaging and translation to complete uninterrupted, are recorded in the Translation Review dashboard report with `Failed` status and error details, and are presented in a non-blocking recovery window with direct folder and report actions. Verified with unit and flow tests; all 163 repository tests pass.

- [x] Add a special flow for the `W07 End of Course Evaluation` assignment: fetch the approved Portuguese version from the PT template through the Canvas API instead of translating the English assignment. Every course should receive the template version; when the assignment exists in the English package, ignore that source file and replace it with the fetched version.
  - Completed 2026-11-02: Added tolerant W07 matching and live Canvas API retrieval from course 11564 assignment 816997; the PT title, description, settings, and LTI launch replace the English package files while course-specific IMSCC linkage is preserved. Verified against a disposable copy of the tracked sample and all 146 repository tests pass.
- [x] Investigate and fix why the link-mapping flow does not save user-added Portuguese external links to the database.
  - Completed 2026-11-02: Reproduced stale full-file rewrites erasing mappings from overlapping flows; user-added links now merge with the latest mapping store under a write lock, save through atomic replacement, and fail visibly on persistence errors. Regression coverage added; all 141 repository tests pass.
- [x] Implement and approve an Office XML round-trip translation flow for Microsoft Word (`.docx`) and Excel (`.xlsx`) files: convert or extract their translatable content to XML, route that XML through the translation pipeline, and rebuild each file in its original DOCX or XLSX format while preserving its structure, formatting, formulas, and other non-translatable data. Include every processed file and its outcome in the final translation report.
  - Completed 2026-11-02: Added controller-called DOCX/XLSX bots backed by the configured XML agent, protected package reconstruction and atomic replacement, Office outcome reporting, failure-report generation, architecture contracts, and round-trip coverage; all 139 repository tests pass.
- [x] Limit every XML/QTI Gemini content package to at most 600 source lines while retaining the existing 8,000-character batching target and safely splitting and reassembling oversized individual nodes.
  - Completed 2026-11-02: Verified the 600-line boundary, multiline-node reassembly, fail-closed payload guard, and all 133 repository tests.

## Watch conditions

- If bots begin using different Gemini API keys or projects, add an actionable backlog item to replace global `genai.configure()` state with per-bot client instances before enabling concurrent calls. This is not currently actionable while all bots share one key.

## Maintenance rules

- Use `[ ]` for open work and `[x]` only after the change has been implemented and verified.
- Keep entries short, actionable, and free of implementation details that belong in `app/App_Architecture.json` or a dedicated design document.
- Add a brief indented completion note with the verification date when closing an item.
- Do not delete completed items; move them to a `Completed` section so the project keeps a lightweight history.
