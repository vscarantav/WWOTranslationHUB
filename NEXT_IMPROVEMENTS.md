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
  - [x] Apply each approved `Variable PT` identifier throughout the translated GitHub repository while preserving external environment keys and platform-defined identifiers.
    - Completed 2026-11-04: The GitHub flow now inventories protected identifiers repository-wide before analysis, seeds explicit no-op mappings for Node.js/deployment/environment contracts, applies ordinary Portuguese identifiers to every supported definition and reference, reports only the value actually applied, and blocks publication on inconsistent or unsafe mappings. Verified with 48 focused GitHub/variable/architecture tests, all 171 repository tests, and an in-memory audit of the 254-row CSE340 Variables report.
  - [x] Rename the `Images and Files` tab to `Resources`, and rename its first cell from `Images` to `Resources`.
    - Completed 2026-11-09: Future GitHub reports and the recovered CSE341 report now use `Resources` for both the worksheet and title cell.
  - [x] Remove the `In U.Images` column.
    - Completed 2026-11-09: The obsolete column was removed from the GitHub resource schema and regression coverage.
  - [x] Move the `Num` column so it is the first column.
    - Completed 2026-11-09: Resource rows are numbered sequentially in the first column.
  - [x] Add `Fix Link` as an option in the `Plan` column dropdown.
    - Completed 2026-11-09: The Plan validation list now includes `Fix Link` in every generated GitHub report.
  - [x] Add `Status` as the second report column, with a `To Do` / `Done` dropdown that defaults to `To Do`.
    - Completed 2026-11-09: Every resource row defaults to `To Do`, supports `To Do` / `Done`, and uses status-specific formatting.
  - The two report models are documented in `app/App_Architecture.json`: `DashboardGenerator` serves IMSCC/EdTech and `GitHubTranslationReportGenerator` serves GitHub. The explicit GitHub resource-layout standard is complete; consolidating the two generator implementations into one cross-flow model remains part of this parent improvement.

## Completed

- [x] Separate API-related instructions from general technical setup instructions in GitHub Resources reports.
  - Completed 2026-11-11: Added `Technical Setup Instruction` to the Package dropdown; defined `API Setting` as instructions that configure, expose, test, document, secure, store data for, or deploy an API; defined the new category for general tooling, repository, linting, project-setup, and workflow guidance; added model classification plus deterministic legacy fallback; and regenerated the CSE341 report with 161 API Setting and 29 Technical Setup Instruction rows. Verified all 208 repository tests.

- [x] Include public links and page-used CSS assets in GitHub Resources reports with accurate package and page-link classifications.
  - Completed 2026-11-11: GitHub report inventory now includes public hyperlinks, GitHub/GitHub Pages, Canvas destinations, and CSS images only on pages whose linked stylesheet selector uses them, while excluding internal navigation, fragments, localhost examples, unused files, and shared BYUI logo references. Regenerated the CSE341 report with 224 rows (190 API Setting, 13 External, 12 GitHub, and 9 Image) and verified all 47 GitHub tests plus all 205 repository tests.

- [x] Make GitHub embedded-code syntax validation baseline-aware and normalize standalone indentation so source-authored Python and JSON examples are not misreported as translation damage.
  - Completed 2026-11-09: Standalone Python snippets are dedented before parsing, and translated snippet errors are reported only when the corresponding source snippet parsed successfully. Verified against all four CSE 341 source-baseline failures, all 41 GitHub tests, and all 199 repository tests.

- [x] Preserve source-exact third-party product interface labels during GitHub translation, including `Database and Network Access`, without triggering unchanged-English failures.
  - Completed 2026-11-09: Approved product UI labels are excluded from translation batches and unchanged-English detection while surrounding instructional prose remains translatable. Verified against the exact CSE 341 MongoDB instruction, focused HTML bot coverage, and the full repository suite.

- [x] Restrict GitHub variable analysis and application to identifier-bearing code contexts so prose-only TXT reflection templates and ordinary English words are never treated as variables.
  - Completed 2026-11-09: TXT mappings now apply only inside explicit fenced/inline code or files with strong raw-code syntax. Verified with the failed run's 211-entry mapping across all seven CSE 341 reflection files with zero replacement-count mismatches, plus focused and full-suite tests.

- [x] Make GitHub variable-analysis retries preserve the source identifier's naming style deterministically instead of repeating invalid lower/camel-case suggestions.
  - Completed 2026-11-09: Model suggestions are normalized to the source identifier convention before validation, single-word lowercase targets are accepted as valid camelCase, and retry prompts include the prior validation error. Verified against the failed `database` and `lastName` suggestions, collision-free integration with the prior report mapping, and all 199 repository tests.

- [x] Fix GitHub HTML validation so the approved target-language `<html lang>` localization is not rejected as protected-attribute drift, with regression coverage for the normalizer-to-validator handoff.
  - Completed 2026-11-09: Root HTML language localization is driven by shared language metadata (`pt-BR` for PTBR, `es` for future SPA, and `fr` for future FRA) and excluded narrowly from generic protected-attribute equality, while nested language and other attribute changes remain blocked. Verified with all 38 GitHub tests, all 191 repository tests, and a scan of all 58 HTML files in the cancelled CSE 341 workspace with zero false structural failures.

- [x] Apply the IMSCC link-mapping and commented-link reporting flow to EdTech book translation.
  - Completed 2026-11-04: EdTech now runs the shared `LinkProcessor` against every extracted HTML file before translation and uses the same unmapped-link dialog, persistent mapping store, automatic rewrites, skip/comment behavior, logging, save-failure handling, and dedicated `Commented Links` report tab as IMSCC. The tab includes both mapped links with comments and skipped links with comments. Verified with 34 focused EdTech/report tests and all 169 repository tests.

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
