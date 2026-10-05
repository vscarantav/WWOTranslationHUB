# GitHub Translation Flow — Implementation Plan

## Status

- Document state: Approved and implemented — ready for a controlled source-repository pilot
- Target application: Course Translation Hub
- Requested flow: GitHub-hosted Software Development textbook translation
- Phase-one target language: Portuguese (PTBR)
- Future target language: Spanish (SPA), disabled until an approved Spanish SD glossary is available
- Source ownership rule: CSE repositories are read-only and must never be written to, edited, or reconfigured
- Phase-one destination: a new public repository in the authenticated user's personal GitHub account
- Implementation is complete; the first live source-repository run remains a controlled pilot.

## How to Review This Document

The answers below are retained as the implementation record. Phase-one decisions in the Status and Conflict Resolution sections are authoritative where an earlier answer was superseded.

## Confirmed Requirements

The new flow must:

1. Add a separate **GITHUB TRANSLATION** section to the Translation Hub UI.
2. Prompt the user for a GitHub repository.
3. Pull or clone the source repository.
4. Run all bots that are relevant to GitHub textbook content.
5. Use a dedicated global Software Development glossary.
6. Require Gemini to return information about variables used on translated pages when code is present.
7. Record the following variable information:
   - Page title
   - Context summary
   - Variable in English (original)
   - Variable in Portuguese (translated or recommended)
8. Apply conditional formatting to highlight duplicate variable entries.
9. Generate a new GitHub repository using an agreed naming convention and push the translated content to it.
10. Generate an Excel report containing exactly these three tabs:
    - `Reviewing`
    - `Variables`
    - `Images and Files`
11. Treat every CSE GitHub repository as a read-only source. The Hub must never push, merge, open a pull request, change settings, enable Pages, or perform any other write operation against a CSE repository.
12. Create translated phase-one repositories only in the authenticated user's personal GitHub account.
13. Enable Portuguese in phase one and keep Spanish visibly disabled until the Spanish global SD glossary is approved.
14. Publish each generated personal repository through GitHub Pages from its `main` branch and repository root.

## Open Questions

### 1. Meaning of “Variable”

What should count as a variable? Please provide two or three real examples. Possibilities include programming identifiers such as `student_name`, placeholders such as `{{ courseName }}`, environment variables, or technical terms used in prose.

**Answer:**
The courses in Software Development have their variables in their teaching content and assignments. these will include coding, configuration, database, and other technical terms. These variables are not yet in the glossary at this point. We will build a glossary of these variables to be used in the IMSCC translation process in the future. 

### 2. Variable Translation Behavior

Should variable identifiers be renamed inside executable code, or should executable identifiers remain unchanged while the report supplies a suggested Portuguese name?

The recommended default is to preserve identifiers in executable code because changing them can break examples unless every definition and reference is updated consistently.

**Answer:** 
My first thought was to send the whole pages to Gemini to translate. The agents would have specific instructions to find any variables and translate them as well, but should include them listed in the AI response. Translation HUB should get them and place them on the variables tab in the report. I don't believe it would be necessary to rename the variables in the executable code. Gemini should be instructed to start and finish the list with something like $$$$ so that we can easily find and extract the list. After extraction, TranslationHUB should remove them from the translated pages so they don't appear as regular text in the translation. 

### 3. Repository Content Scope

Which repository content should be translated?

Please clarify whether the scope is:

- Only a specific directory such as `docs/`
- All `.md` and `.mdx` files
- Framework navigation/configuration files such as `mkdocs.yml`, Docusaurus sidebars, JSON, or YAML
- Human-readable text inside React/JSX components
- Other file types

**Answer:** this is an example: https://byui-cse.github.io/cse340-ww-course-v2/index.html


### 4. Example Repository and Frameworks

Please provide one or more representative GitHub repository URLs. Are all source repositories organized the same way, or must the Hub support multiple documentation frameworks?

**Answer:** https://byui-cse.github.io/cse340-ww-course-v2/index.html
https://byui-cse.github.io/cse341-ww-course-v2/index.html


### 5. Target Languages

Is this flow Portuguese-only, or should it offer the existing PTBR and SPA choices? 

**Answer:** BOTH PT and SPANISH. it should use the same process as in IMSCC files (translate - review content - Review glossary)

**Phase-one decision:** Implement Portuguese first. Keep Spanish disabled until the Spanish SD glossary is ready.


### 6. Software Development Glossary

Will an SD glossary be supplied? If so, what is its format and location? If not, should the initial implementation create `Glossary/software_development.json` and seed it with approved terms?

**Answer:** I've added the folder sd_glossary to my GitHub as I thought might be necessary for the project. GITHUB should use @global-sd-glossary only. the other glossaries that will be added later are for SD specific IMSCC translations that are not yet implemented to translation HUB.


### 7. Destination Repository Name

What is the exact naming convention? For example, should `cse111-course` become `cse111-course-pt`, `cse111-course-PTBR`, or another form?

**Answer:**
it should relace the V2 with pt like: 
https://byui-cse.github.io/cse340-ww-course-v2/index.html
https://byui-cse.github.io/cse340-ww-course-pt/index.html

But for testing purposes, replace the v2 with test1 so it does not overwrite the original repository.

### 8. Destination Owner and Visibility

Where should the new repository be created: the source organization, a fixed organization, or the authenticated GitHub user's account? Should it be public or private?

**Answer:**
authenticated GitHub user's account
Public

### 9. Existing Destination Repository

What should happen if the destination repository already exists: stop with an error, update it, create a new branch, or generate a numbered name?

**Answer:**
create a new branch DEV-VSR


### 10. Push and Pull Request Behavior

Should the Hub push directly to the default branch, or push a translation branch and open a pull request?

**Answer:**
push directly to the DEV-VSR branch

### 11. GitHub Authentication

Should the Hub use a GitHub personal access token stored in `.env`, another credential provider, or the user's existing Git credential manager? Repository creation requires an authenticated GitHub API operation; the GitHub CLI is not currently installed.

**Answer:**
GitHub personal access token and as it does with the CANVAS_API it should prompt the user for the token in case it is empy in .env file.

### 12. Reviewing Tab

Should `Reviewing` use the existing report columns below, or a different structure?

| Proposed column | Purpose |
| --- | --- |
| Page Name | Translated page title |
| Type | Markdown, MDX, navigation, or other content type |
| Link EN | Source repository page or file link |
| Link PT | Destination repository page or file link |
| Status | Translated, Student Reviewed, or Professionally Reviewed |

**Answer:**
use this structure

### 13. Variables Tab

Please confirm the proposed columns:

| Proposed column | Purpose |
| --- | --- |
| Page Title | Title of the page containing the variable |
| Context Summary | Short explanation of how the variable is used |
| Variable EN | Original identifier or variable |
| Variable PT | Translated or recommended identifier |
| Source File | Repository-relative path for traceability |

Should any columns be added or removed?

**Answer:**
Nope, that is good enough

### 14. Duplicate Highlighting

Should Excel highlight:

- Every duplicate in `Variable EN` and `Variable PT` independently
- Only one English variable mapped to multiple Portuguese translations
- Only multiple English variables mapped to the same Portuguese translation
- All of the above, using different colors

**Answer:**


### 15. Images and Files Tab

Please confirm which fields are required. The proposed fields are:

| Proposed column | Purpose |
| --- | --- |
| Page Title | Page referencing the asset |
| Source File | Page's repository-relative path |
| Asset Path or URL | Referenced image or file |
| Asset Type | Image, PDF, download, video, or other |
| Alt Text EN | Original alt text |
| Alt Text PT | Translated or generated alt text |
| Status | Copied, translated, missing, external, or error |
| Notes | Review information |

**Answer:**

Replicate the supplied Images worksheet model inside the `Images and Files` tab.

The worksheet must contain:

1. A merged blue title row labeled `Images`.
2. The instruction row from the reference model explaining that images must be checked for English text or US-locale formatted numbers and may need recreation or an alternate translated URL.
3. These columns, in this order:

   | Column | Required behavior |
   | --- | --- |
   | `In U.Images` | Unique-images indicator/count |
   | `Images (Copy from UniqueImages)` | Image or file path/URL |
   | `Package` | Dropdown; default value is `GitHub` |
   | `Has Text` | Dropdown; blank by default |
   | `Plan` | Dropdown; blank by default |
   | `TL Link` | Published translated GitHub Pages site |
   | `Resource Link` | Clickable direct link to the published image/file, or its original external URL |
   | `Notes` | Reviewer notes |
   | `Num` | Sequential row number |

4. The `Package` dropdown must contain:
   - `BrightSpot`
   - `Canvas`
   - `External`
   - `GitHub`
   - `LLDOC`
5. The `Has Text` dropdown must contain:
   - `- NA`
   - `No`
   - `Yes`
6. The `Plan` dropdown must contain:
   - `Find Equivalent`
   - `Recreate`
   - `Remove`
   - `Remove Text`
   - `Request Translate`
   - `Use Current`



### 16. Image Processing

Should existing image alt text be translated? Should missing alt text be generated in English and then translated, as the current HTML image bot does?

**Answer:**
Yes and Yes

### 17. Meaning of “Run All Bots”

Which operations are required for GitHub repositories? The recommended interpretation is to run every applicable capability—not IMSCC/XML-only bots—including translation, glossary enforcement, link processing, image/alt-text processing, variable extraction, validation, and reporting.

**Answer:**
Same bots that run in IMSCC file when applicable - including scriptures, HTML, XML, TXT, glossary, etc. makes sense?

### 18. Failure and Publication Policy

If one or more pages fail after retries, should the Hub stop without creating/pushing the destination repository, or push the successful files with failures identified in the report?

The recommended default is to stop before publication when a critical translation or structural-validation error remains.

**Answer:**
use the recommended default - and put on report the files that failed. 

## Answer Review — Conflicts and Follow-Up Decisions

Most workflow decisions are clear. The following items must be resolved before implementation so the code and acceptance tests do not rely on assumptions.

### A. Variables Versus Technical/Glossary Terms

Answers 1 and 2 currently combine two different concepts:

- Executable identifiers, placeholders, configuration keys, database identifiers, and similar code-level variables
- Technical vocabulary used in teaching prose, such as `authentication`, `database`, or `framework`

The current plan assumes deterministic extraction of code-level identifiers. If the `Variables` tab is intended to collect broader glossary candidates, the extraction rules and expected number of rows will be substantially different.

Recommended resolution: classify both, preserve executable identifiers in code, and add every in-scope code/config/database identifier or technical glossary candidate to the report with a category. Adding a `Category` column would conflict with the five-column structure approved in Answer 13, so either the category must be omitted or that structure must be revised.

**Resolution:**
do whatever is best. just to give you some more context: Github and Canvas will share content. sometimes variables like student_id could be translated as either aluno_id or id_estudante. so the goal is to make sure variables are consistent. the flow will be - we translate github, analyze and correct any issues like this of student_id. then we build a glossary to be used in canvas, with the appropriate variable names.

### B. Gemini Response Envelope

The `$$$$` markers describe the desired separation between translated content and extracted variable records, but the implementation plan currently specifies a structured JSON response. Both approaches solve the same problem, but implementing both would be redundant and fragile.

Recommended resolution: use one structured response envelope containing `translated_content` and `variables`. The Hub writes only `translated_content` to the translated page, so metadata cannot leak into the page. Sentinel markers can be retained only as a fallback parser if Gemini does not reliably return structured JSON.

**Resolution:**
Use whatever is more reliable


### C. Source URL and Translation Scope

Answers 3 and 4 provide published GitHub Pages URLs. The Hub accepts these standard `owner.github.io/repository/...` links, derives the corresponding `github.com/owner/repository` clone URL, and authenticates the read-only clone with the configured token. Direct repository URLs remain supported.

The runtime link may be either a direct GitHub repository URL or its standard GitHub Pages project URL. Phase one reads the repository's Pages configuration, clones the configured source branch, scans only the configured Pages source directory for supported HTML, Markdown, MDX, XML, and TXT content, and copies that directory's other non-ignored files unchanged. The Pages directory is flattened into the destination repository root so the approved `main:/` publication setting works.

**Resolution:**

The user now has access to the private CSE repositories and will supply or select the actual repository URL at runtime. Access is strictly read-only: the Hub may authenticate, clone, fetch, and inspect the source repository, but it must never write to it or change its settings.

Repository-specific content scope will be finalized during the first authenticated pilot after the scanner inventories the actual framework and file types. Until then, the architecture must remain file-type aware and run only applicable translation bots.


### D. Spanish Naming, Glossary, and Report Labels

Answer 5 confirms PTBR and Spanish, but the following requirements are currently Portuguese-only:

- Destination naming defines `v2` to `pt`, with no Spanish suffix.
- The Variables sheet defines `Variable PT`, with no Spanish equivalent.
- `global-sd-glossary 1.md` currently contains English, Portuguese (Brazil), and Context columns only.

Recommended resolution: define a Spanish repository suffix, add approved Spanish translations to the global SD glossary, and make the report column dynamic (`Variable PT` or `Variable ES`) based on the selected run language.

**Resolution:**
Spanish will use the `spa` suffix. Phase one is Portuguese-only. Spanish controls remain disabled until `global-sd-glossary` includes approved Spanish translations. When enabled later, report labels will be language-aware (for example, `Variable PT` or `Variable SPA`).


### E. Destination Repository, Branch, and Published Site

Answers 7–10 establish a public repository under the authenticated user's account and direct pushes to `DEV-VSR`. A repository under that account will have a Pages URL under that user's namespace, not `byui-cse.github.io`. In addition, a new repository and an existing repository require slightly different branch behavior.

Please confirm:

1. Whether the Hub must configure and publish GitHub Pages, or only create/push the repository.
2. Whether a newly created repository should also receive only the `DEV-VSR` branch.
3. Which branch `DEV-VSR` should be based on when the destination already exists.
4. What to do if `DEV-VSR` already exists.
5. Whether `test1` is the temporary suffix for both languages, and what the production Spanish suffix will be.

**Resolution:**
Phase-one publication rules:

1. Never create, push, merge, or configure Pages in the CSE source repository.
2. Always create a new public repository in the authenticated user's personal GitHub account.
3. For a Portuguese test run, transform a name such as `cse340-ww-course-v2` into `cse340-ww-course-test1-pt`.
4. If that personal destination name already exists, create `cse340-ww-course-test1-pt-2`, then `-3`, and so on. Do not update or overwrite the existing repository.
5. Push translated content to the new repository's `main` branch.
6. Configure GitHub Pages to publish from the `main` branch and repository root.
7. Do not use `DEV-VSR` during this new-repository phase-one flow. Existing-repository branch behavior is deferred until a future workflow explicitly requires updating an existing translated repository.
8. The future production Portuguese convention replaces `v2` with `pt`. The future Spanish suffix is `spa`, but Spanish remains disabled in phase one.

### F. Duplicate Highlighting

Answer 14 is blank. The exact duplicate conditions and colors are therefore still undefined.

Recommended resolution: use different colors for (1) duplicate English entries, (2) one English entry mapped to multiple target-language values, and (3) multiple English entries mapped to the same target-language value.

**Resolution:**
- Every duplicate in `Variable EN` and `Variable PT` independently -> No, highlight only EN duplicates. do not analyze or color PT variable.
- Only one English variable mapped to multiple Portuguese translations -> NO
- Only multiple English variables mapped to the same Portuguese translation -> NO
- All of the above, using different colors - > NO

### G. Images, Files, and Alt Text

Answer 15 now defines an exact image-review model, while Answer 16 requires translation and generation of alt text. The reference model has no `Alt Text EN` or `Alt Text PT/ES` columns. The tab is also named `Images and Files`, but the supplied model is image-specific.

Please confirm whether:

1. Alt text values should be recorded in `Notes`, omitted from the report after processing, or added as new columns. -> Should be added as new columns
2. Non-image downloads such as PDFs should use the same rows and dropdowns. -> YES
3. `In U.Images` is a numeric count/indicator populated by the Hub, and how it should be calculated for GitHub content. -> YES

**Resolution:**

`U.Images` most likely means a separate centralized **Unique Images** inventory. This interpretation comes from the adjacent headers `In U.Images` and `Images (Copy from UniqueImages)`. Under that model:

- `1` probably means the asset has one matching entry in the Unique Images inventory.
- `0` would mean it was checked and no match was found.
- A value greater than `1` could indicate duplicate matches that require review.
- It is not necessarily the number of times the image appears within the GitHub repository.

The exact behavior cannot be confirmed from the screenshot alone because no Unique Images catalog or source workbook has been supplied. Using the repository usage count in this column would risk giving the column the wrong meaning.

Recommended phase-one behavior: preserve the `In U.Images` column for compatibility but leave it blank unless an authoritative Unique Images inventory is supplied. The Hub may calculate repository usage counts internally, but it should not place them in `In U.Images` without confirmation.


### H. Failed Files in the Three-Tab Report

Answer 18 requires failed files to appear in the report, but the approved `Reviewing` structure has no failure-details column and its current status choices are review stages.

Recommended resolution: add `Failed` as a Status option and add a `Notes / Error` column to `Reviewing`, or store the error as an Excel cell comment if the five-column structure must remain exact.

**Resolution:**
YES

## Existing Architecture Findings

The current application has three top-level Tkinter workflows:

- Canvas IMSCC translation
- EdTech Master translation
- Quality Assurance audit

The existing `TranslationController` and `WorkspaceManager` are strongly oriented toward IMSCC and directory translation. `TranslationController.process_directory()` always prepares Canvas-specific content and packages its output as an IMSCC file. The GitHub flow should therefore have its own orchestrator and repository workspace instead of calling the full IMSCC directory pipeline.

Relevant reusable components include:

- Gemini retry and success tracking
- Glossary filtering
- Translation logging
- HTML text and image processing patterns
- Concurrent file processing with sequential retry
- Excel formatting conventions
- Tkinter background-thread and console-output patterns

Git is installed in the runtime environment. The GitHub CLI is not installed, so repository creation should use the GitHub REST API unless the authentication decision specifies another mechanism. Standard Git commands can still be used for clone, branch, commit, and push.

The architecture JSON already includes an older draft for GitHub textbook translation. It should be replaced or updated because it does not cover automatic remote repository creation, structured variable collection, or the required three-tab report.

## Proposed Architecture

```text
GitHub Translation UI
        |
        v
GitHubTranslationController
        |
        +--> GitHubRepositoryManager
        |      +--> validate URL/authentication and source ownership
        |      +--> clone CSE source through a read-only path
        |      +--> remove all source push capability from the workspace
        |      +--> create a new destination in the user's account
        |      +--> commit, push, and enable Pages only on the destination
        |
        +--> RepositoryScanner
        |      +--> detect framework
        |      +--> classify translatable/protected/copied files
        |      +--> build source manifest
        |
        +--> MarkdownTranslationBot
        |      +--> protect code and syntax
        |      +--> apply global + SD glossary
        |      +--> translate human-readable segments
        |      +--> return structured variable records
        |
        +--> GitHubContentValidators
        |      +--> source/output completeness
        |      +--> protected-token integrity
        |      +--> Markdown/MDX structural checks
        |      +--> variable-response completeness
        |
        +--> GitHubTranslationReport
               +--> Reviewing
               +--> Variables
               +--> Images and Files
```

## Proposed File Changes

Names are provisional and may change during implementation.

### New Files

| File | Responsibility |
| --- | --- |
| `app/github_translation_controller.py` | Orchestrate the complete GitHub translation transaction |
| `app/core/github_repository_manager.py` | Clone, remote creation, commit, and push operations |
| `app/core/github_repository_scanner.py` | Framework detection, file classification, and source manifest generation |
| `app/core/github_content_validator.py` | Verify translated repository completeness and structural integrity |
| `app/core/github_report_generator.py` | Generate the required three-tab Excel workbook |
| `app/bots/markdown_bot.py` | Translate Markdown/MDX while preserving syntax and code |
| `app/bots/variable_extraction.py` | Define, normalize, validate, and aggregate structured variable records |
| `tests/test_github_repository_manager.py` | Repository and authentication behavior tests |
| `tests/test_github_repository_scanner.py` | File discovery and framework detection tests |
| `tests/test_markdown_bot.py` | Markdown/MDX preservation and translation tests |
| `tests/test_github_report_generator.py` | Workbook tabs, columns, and conditional-formatting tests |
| `tests/test_github_translation_controller.py` | End-to-end orchestration with mocked network/API calls |

### Modified Files

| File | Change |
| --- | --- |
| `app/main_ui.py` | Add the GitHub Translation section and workflow dialogs |
| `app/App_Architecture.json` | Add the implemented architecture and authoritative operating rules; mark the older embedded proposal as superseded |
| `.gitignore` | Exclude temporary GitHub workspaces and credential-bearing artifacts |
| `requirements.txt` | Add a Markdown parser or GitHub SDK only if the final design requires one |

The existing IMSCC controller should not be expanded with GitHub clone/push behavior. Reusable logic can be extracted later if doing so remains low-risk and does not alter the established Canvas and EdTech flows.

## Detailed Implementation Phases

### Phase 1 — Finalize Contracts and Samples

1. Resolve every open question above.
2. Obtain at least one representative source repository.
3. Record supported repository structures and frameworks.
4. Define the precise variable taxonomy.
5. Approve workbook columns and duplicate rules.
6. Define destination naming, ownership, visibility, and existing-repository behavior.
7. Define the publishing failure policy.

**Exit criteria:** Requirements are specific enough to write fixtures and acceptance tests without guessing.

### Phase 2 — Repository Workspace and GitHub Integration

1. Validate direct repository URLs and standard GitHub Pages project URLs; normalize either form to a canonical HTTPS Git clone URL and reject unsupported schemes or ambiguous paths.
2. Validate Git availability and authentication before starting an expensive translation.
3. Verify the source and destination owners are different and reject any destination in the CSE organization.
4. Create a per-run workspace under a dedicated `github_workspace` directory.
5. Clone the selected CSE branch without embedding secrets in command output.
6. Treat the clone as input only: do translation in a separate tree with no source `.git` directory or writable source remote.
7. Remove or disable the source remote's push URL as a defense-in-depth safeguard.
8. Capture source owner, repository, branch, and commit SHA for traceability.
9. Derive a personal destination name using `-test1-pt`, adding `-2`, `-3`, and so on when needed.
10. Implement authenticated creation of a new public repository under the authenticated user's personal account.
11. Initialize destination history separately, commit to `main`, and push only to the newly created personal repository.
12. Configure GitHub Pages only on the new personal repository, using `main` and the repository root.
13. Keep publication as the final phase so partial output is not pushed accidentally.

**Exit criteria:** A mocked integration test can clone a fixture, plan a destination, create a mocked remote, and construct the expected push operation without exposing credentials.

### Phase 3 — Repository Discovery and Manifest

1. Read the source repository's GitHub Pages configuration and walk only its configured publication directory while excluding `.git`, dependencies, build outputs, generated files, caches, and other approved ignore patterns.
2. Detect the documentation framework from known configuration files.
3. Classify each file as:
   - Translatable
   - Copied unchanged
   - Protected source code
   - Ignored/generated
   - Unsupported and requiring review
4. Parse Markdown and MDX references to images and downloadable files.
5. Generate a stable source manifest containing paths, hashes, content type, and planned action.

**Exit criteria:** The scanner produces deterministic results for each supported fixture repository.

### Phase 4 — Software Development Glossary

1. Load only the approved `global-sd-glossary` for the GitHub flow.
2. Support Portuguese entries and terms that must remain in English.
3. Do not merge course-specific SD glossaries intended for future IMSCC translation.
4. Detect duplicate or conflicting global SD entries and fail or report them according to an agreed rule.
5. Send only relevant global SD terms with each page request to control prompt size.
6. Keep Spanish disabled until the same global glossary contains approved Spanish entries.

**Exit criteria:** Tests prove that preserve-in-English terms and required translations reach the Markdown bot correctly.

### Phase 5 — Markdown and MDX Translation

1. Parse content into translatable and protected segments.
2. Protect:
   - Fenced and indented code blocks
   - Inline code
   - URLs and link destinations
   - HTML/JSX tag and attribute syntax
   - MDX expressions and imports/exports
   - Frontmatter keys and non-translatable values
   - Template delimiters and known placeholders
3. Translate headings, paragraphs, list text, table prose, captions, callouts, link labels, and approved metadata fields.
4. Use bounded batches for large pages.
5. Restore protected values exactly.
6. Retry Gemini responses that are malformed, incomplete, suspiciously short, or missing required records.
7. Save files only after page-level validation succeeds.

**Exit criteria:** Complex fixture files retain valid syntax and byte-identical protected sections while their human-readable content is translated.

### Phase 6 — Structured Variable Collection

1. Define a structured JSON response schema for Gemini.
2. Require each page response to include:
   - Page title
   - Context summary
   - Source file
   - English variable
   - Portuguese variable or recommendation
3. Run deterministic extraction over protected code and placeholders as a completeness check.
4. Compare deterministic findings with Gemini's response.
5. Retry when required variables are missing.
6. Normalize whitespace and quoting without collapsing identifiers that differ by case.
7. Aggregate records across the repository while retaining page-level provenance.
8. Detect one-to-many and many-to-one translation inconsistencies for reporting.

**Exit criteria:** Every deterministically detected in-scope variable is represented in the result or explicitly classified as intentionally untranslated.

### Phase 7 — Images, Files, and Links

1. Inventory local and remote image/file references.
2. Verify that relative local assets exist.
3. Copy repository assets without unnecessary recompression or mutation.
4. Translate existing alt text if approved.
5. Generate missing alt text if approved.
6. Preserve external URLs unless an explicit localization mapping applies.
7. Record asset status and review notes for the report.
8. Validate that translated relative links still resolve within the destination tree.

**Exit criteria:** Referenced local assets are present and internal translated links resolve or appear as actionable report errors.

### Phase 8 — Three-Tab Excel Report

1. Create a GitHub-specific report generator.
2. Generate exactly:
   - `Reviewing`
   - `Variables`
   - `Images and Files`
3. Add frozen headers, filters, sensible widths, wrapped text, and consistent status formats.
4. Add status dropdowns and status-based conditional formatting to `Reviewing` if approved.
5. Add formula-based conditional formatting for the approved duplicate conditions in `Variables`.
6. Reproduce the approved Images worksheet presentation inside `Images and Files`, including the blue merged title and instruction row.
7. Add the `Package` dropdown with `GitHub` preselected and the approved five options.
8. Add blank-by-default `Has Text` and `Plan` dropdowns with the approved option lists.
9. Add source and destination hyperlinks where available.
10. Ensure empty-result sheets still contain headers and explanatory status rather than being omitted.

**Exit criteria:** Automated workbook inspection confirms the exact sheet names, column order, validations, formulas, and conditional-formatting rules.

### Phase 9 — Validation and Atomic Publication

1. Compare the output tree against the source manifest.
2. Confirm every planned file was translated, copied, or deliberately ignored.
3. Confirm protected code and syntax survived unchanged unless code-variable translation is explicitly approved.
4. Run Markdown/MDX structure checks.
5. Confirm the report was generated successfully.
6. Block publication on critical errors according to the approved failure policy.
7. Reconfirm that the destination owner is the authenticated user and is not the CSE source organization.
8. Create a new numbered personal repository only when appropriate.
9. Commit translated content to a separately initialized `main` branch with a deterministic message containing the source repository and commit reference.
10. Push only to the new personal destination.
11. Configure GitHub Pages from `main` and the repository root, wait for GitHub to confirm a public `built` deployment, then capture GitHub's published URL.
12. Return the repository URL, Pages URL, report path, and summary counts to the UI.

**Exit criteria:** A successful run produces a traceable destination repository and workbook; a failed run never silently publishes incomplete content.

### Phase 10 — UI Integration

1. Add a dedicated `GITHUB TRANSLATION` `LabelFrame` to the main window.
2. Enable Portuguese and display Spanish as disabled with a “Spanish glossary required” explanation.
3. Add a **Select / Start GitHub Translation** button.
4. Prompt for repository URL and any required branch or destination settings.
5. Validate required fields before disabling the UI.
6. Run translation on a background thread.
7. Stream sanitized phase/file percentages to the existing console and shared determinate progress bar.
8. Include the new button in the shared enable/disable lifecycle.
9. Present a completion dialog containing repository and report links.
10. Present clear recovery guidance on clone, authentication, translation, validation, or push failures.

**Exit criteria:** The UI remains responsive, prevents duplicate concurrent starts, and always restores button state after success or failure.

### Phase 11 — Documentation and Rollout

1. Update the architecture JSON with the final workflow and file ownership.
2. Remove or replace the stale pending GitHub proposal.
3. Document required environment-variable names without committing credentials.
4. Document supported repository frameworks and known exclusions.
5. Add operator instructions for authentication, reruns, conflicts, and failed publications.
6. Pilot the flow with a representative repository before broad use.

**Exit criteria:** A new operator can configure and run the flow using checked-in documentation without developer assistance.

## Error Handling and Recovery

| Failure point | Expected behavior |
| --- | --- |
| Invalid repository URL | Reject before starting and identify the required format |
| Authentication unavailable | Stop before cloning private content or translating |
| Clone failure | Preserve diagnostic details without exposing credentials |
| Unsupported repository structure | Stop or request confirmation before translating unknown files |
| Gemini page failure | Retry concurrently, then retry failed pages sequentially |
| Invalid Markdown/MDX response | Restore the untouched source for that page and mark the run failed |
| Missing variable records | Retry structured extraction and record an explicit validation failure |
| Missing local asset | Add a report error and apply the approved publication policy |
| Personal destination name already exists | Select the next available numbered repository name; do not write to the existing repository |
| Report generation failure | Do not publish |
| Remote creation succeeds but push fails | Preserve local output and report remote state clearly; never delete or overwrite automatically |

## Security Requirements

1. Never place access tokens in repository URLs, logs, workbooks, exceptions, or generated files.
2. Read credentials from the approved credential source at runtime.
3. Use the narrowest GitHub token permissions compatible with repository creation and push.
4. Never commit `.env` or temporary credential helpers.
5. Sanitize subprocess output before sending it to the UI console.
6. Validate local workspace paths before cleanup or replacement.
7. Do not overwrite an existing local or remote repository without an explicit approved policy.
8. Never issue a Git push, GitHub content mutation, pull request, settings mutation, Pages mutation, or repository mutation against the CSE source owner.
9. Keep source and destination Git repositories separate; translated output must not retain the source clone's `.git` directory.
10. Validate the destination owner immediately before every GitHub write operation.
11. Disable or remove the source remote push URL immediately after cloning so an accidental generic `git push` cannot target CSE.

## Automated Test Plan

### Repository Management

- Accept supported HTTPS repository URLs.
- Reject malformed or unsupported URLs.
- Derive the correct source and destination metadata.
- Avoid credentials in constructed commands and logs.
- Handle public and private clone behavior.
- Reject any write destination owned by the CSE source organization.
- Prove that the source clone has no usable push path after setup.
- Select `-2`, `-3`, and subsequent personal repository names without mutating existing repositories.
- Mock personal remote creation, `main` commit/push, and GitHub Pages configuration.

### Discovery

- Detect every supported framework.
- Include approved content directories and configuration files.
- Exclude `.git`, dependency, cache, and generated directories.
- Classify Markdown, MDX, source code, images, downloads, and unknown files.
- Produce a deterministic manifest.

### Markdown/MDX Translation

- Preserve fenced code blocks with different fence lengths and languages.
- Preserve indented code, inline code, URLs, and link destinations.
- Preserve frontmatter keys and protected values.
- Preserve JSX/MDX syntax, imports, exports, and expressions.
- Translate headings, lists, tables, callouts, and link labels.
- Handle nested formatting and escaped characters.
- Retry malformed or incomplete model output.

### Variables

- Detect each approved variable form.
- Require structured Gemini records when code is present.
- Detect missing Gemini records through deterministic comparison.
- Preserve page title, context, and source provenance.
- Identify inconsistent one-to-many and many-to-one mappings.

### Images and Files

- Inventory local and remote references.
- Identify missing assets.
- Preserve binary files unchanged.
- Translate or generate alt text according to the final decision.
- Validate relative links after output generation.

### Excel Report

- Generate exactly three sheets in the required order.
- Generate correct headers even when a sheet has no data.
- Apply filters, frozen panes, and widths.
- Apply the approved duplicate conditional formatting.
- Apply review-status validation and colors if approved.
- Default every populated `Package` cell to `GitHub` and validate it against the approved list.
- Leave `Has Text` and `Plan` blank while attaching their approved dropdown lists.
- Produce valid hyperlinks without exposing local secrets.

### Orchestration and UI

- Stop publication on critical validation errors.
- Re-enable all buttons after success and failure.
- Prevent duplicate concurrent runs.
- Display sanitized progress and actionable errors.
- Return the report and repository links after success.
- Keep Spanish unavailable until an approved Spanish global SD glossary is detected.

## Manual Acceptance Scenarios

1. Translate a small public Markdown repository containing prose, links, images, inline code, and fenced code.
2. Translate a representative production textbook repository using its actual framework.
3. Verify that executable code remains correct under the approved variable policy.
4. Compare source and destination rendering page by page.
5. Confirm the SD glossary is followed consistently.
6. Confirm every in-scope variable appears in the report with correct context.
7. Confirm duplicate mappings receive the approved highlighting.
8. Confirm local and remote assets appear in `Images and Files` with accurate statuses.
9. Confirm the destination naming, owner, visibility, branch, and commit history.
10. Confirm no source-repository write APIs or push commands are invoked during a complete run.
11. Simulate an authentication failure, Gemini failure, malformed Markdown response, missing asset, and push failure.

## Definition of Done

The GitHub Translation flow is complete when:

- The dedicated UI section can start and monitor the flow.
- The Hub safely clones an approved GitHub textbook repository.
- The CSE source repository remains unchanged and has no usable push path from the translation workspace.
- Supported prose is translated using the global SD glossary.
- Code and framework syntax follow the approved preservation policy.
- Gemini returns the required variable information, backed by completeness validation.
- The translated repository passes structural and completeness checks.
- The Excel workbook contains exactly the approved three tabs and formatting.
- A new numbered public repository is created in the authenticated user's personal account, pushed on `main`, and published through GitHub Pages.
- Spanish remains disabled until the approved Spanish global SD glossary is present.
- Credentials never appear in logs, reports, Git configuration, or generated content.
- Automated tests pass and the representative manual acceptance run is approved.
- The architecture and operator documentation describe the implemented behavior.

## Final Approval

After the answers above are incorporated, use this section to approve implementation.

- Requirements approved by:
- Date:
- Approved source repository/example:
- Approved destination convention:
- Additional constraints:
