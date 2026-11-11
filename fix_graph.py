import re

with open("TranslationHUB_Flow_Final.html", "r", encoding="utf-8") as f:
    content = f.read()

graph_text = r"""flowchart LR
    classDef human fill:#3d1a20,stroke:#ff6b81,stroke-width:2px,color:#ffd6dc
    classDef auto fill:#0f2d1e,stroke:#26de81,stroke-width:2px,color:#b8f5d8
    classDef bot fill:#2d2700,stroke:#ffd32a,stroke-width:2px,color:#fff4b8
    classDef conditional fill:#0e1f36,stroke:#45aaf2,stroke-width:2px,stroke-dasharray:5 5,color:#b8dcf8

    StartNode((Start Hub))

    subgraph Path0 ["0. HUB Updates"]
        direction LR
        Input0["Human: Check for Updates"]
        subgraph Auto0 ["FAST-FORWARD AND RESTART"]
            direction LR
            CheckRemote["Verify Remote and Username"]
            GitFetch["Git Fetch origin main"]
            GitMerge["Fast-Forward Merge"]
            RestartApp["Restart Translation HUB"]
            CheckRemote --> GitFetch --> GitMerge --> RestartApp
        end
        Input0 --> CheckRemote
    end

    subgraph Path1 ["1. Canvas IMSCC Translation"]
        direction LR
        Input1["Human: Select IMSCC and Lang"]
        CsePrompt{"CSE Course?"}
        CseGlossSelect["Human: Select Optional CSE Glossary"]

        subgraph Auto1 ["AUTOMATED IMSCC PIPELINE"]
            direction LR
            Extract1["WorkspaceManager: Extract and Parse context.xml"]
            GroupCheck1["Collect Group Configs (Canvas API)"]
            LinkP_Pre1["LinkProcessor: Pre-process links and link_mapping.json"]
            SpecialPages1["Apply W07 Evaluation and Attention Messaging Templates"]

            subgraph FileLoop1 ["Parallel File Translation Loop (ThreadPool max_workers=3)"]
                direction TB
                AuditGL1["GlossaryAuditBot: Extract Terms"]
                AuditSC1["ScriptureCheckBot: Extract Scriptures"]

                subgraph AITranslators1 ["Specialized Bots (Gemini 3.5 Flash)"]
                    direction TB
                    HTMLBot1["HTMLTranslationAgent (Full and Chunked)"]
                    XMLBot1["XMLTranslationAgent (XML and QTI, max 600 lines)"]
                    TXTBot1["TextTranslationAgent"]
                    OfficeBot1["DOCX and XLSX TranslationBots"]
                end

                CSEPostPass1["CSEGlossaryAgent: Terms Post-Pass"]

                AuditGL1 --> AuditSC1
                AuditSC1 --> HTMLBot1 & XMLBot1 & TXTBot1 & OfficeBot1
                HTMLBot1 & XMLBot1 & TXTBot1 & OfficeBot1 --> CSEPostPass1
            end

            Repack1["WorkspaceManager: Repackage .imscc"]
            Dash1["DashboardGenerator: Multi-tab Excel Report"]

            Extract1 --> GroupCheck1 --> LinkP_Pre1 --> SpecialPages1 --> FileLoop1
            FileLoop1 --> Repack1 --> Dash1
        end

        ManualImport1["Human: Import to Canvas"]
        GroupDecision1{"Has Groups?"}
        AutoMigrate1["Canvas Group Migration (Canvas API)"]
        Checklist1["Human: Review Post-Translation Checklist"]

        Input1 --> CsePrompt
        CsePrompt -- Yes --> CseGlossSelect --> Extract1
        CsePrompt -- No --> Extract1
        Dash1 --> ManualImport1
        ManualImport1 --> GroupDecision1
        GroupDecision1 -- Yes --> AutoMigrate1 --> Checklist1
        GroupDecision1 -- No --> Checklist1
    end

    subgraph Path2 ["2. EdTech Master Translator"]
        direction LR
        Input2["Human: Select Lang and Enter Shell URL"]
        CheckpointCheck2{"Resume Checkpoint?"}

        subgraph Auto2 ["AUTOMATED SCRAPING AND INJECTION (Playwright)"]
            direction LR
            Scrape2["EdTechScraperBot: Extract CodeMirror Chapters"]
            Piggyback2["Prepend Hidden Metadata (Title and Subtitle)"]
            LinkP2["LinkProcessor: Shared link_mapping.json"]

            subgraph EdTechLoop2 ["HTML Chunk Translation (Gemini 3.5 Flash)"]
                direction TB
                ETChunkBot["HTMLTranslationAgent (Chunked Mode, max 6000 chars)"]
                ETVerifyEN["Unchanged English Detection and Retries"]
                ETChunkBot --> ETVerifyEN
            end

            ETReport2["EdTech Translation Report"]
            Inject2["EdTechScraperBot: Inject CodeMirror Chapters and Save"]
            Verify2["Reopen Editor and Verify Persisted Content"]

            Scrape2 --> Piggyback2 --> LinkP2 --> EdTechLoop2 --> ETReport2 --> Inject2 --> Verify2
        end

        Checklist2["Human: Review EdTech Checklist"]
        Input2 --> CheckpointCheck2
        CheckpointCheck2 -- New Run --> Scrape2
        CheckpointCheck2 -- Resume --> Inject2
        Verify2 --> Checklist2
    end

    subgraph Path3 ["3. Quality Assurance Audit"]
        direction LR
        Input3["Human: Select EN and Translated IMSCCs"]

        subgraph Auto3 ["AUTOMATED QA AUDIT"]
            direction LR
            Extract3["CourseAuditor: Extract and Index Manifests"]

            subgraph QAPairing3 ["Multi-Step File Matching"]
                direction TB
                PairManifest["Match by Resource ID"]
                PairPath["Match by Relative Path"]
                PairAI["QAAuditBot: AI File Pairing (e.g. W03 to S03)"]
                PairManifest --> PairPath --> PairAI
            end

            subgraph QALoop3 ["Auditing Engines"]
                direction TB
                LinksAudit3["Strict Link Audit: URL Comparison"]
                ContentAudit3["QAAuditBot: LLM Semantic and Content Audit"]
            end

            subgraph QAReport3 ["Excel QA Report"]
                direction TB
                Sheet1["Page Audit Report"]
                Sheet2["Content Audit Report"]
                Sheet3["Links Audit Report"]
            end

            Extract3 --> QAPairing3 --> QALoop3
            QALoop3 --> Sheet1 & Sheet2 & Sheet3
        end

        End3(((Audit Complete)))
        Input3 --> Extract3
        Sheet1 & Sheet2 & Sheet3 --> End3
    end

    subgraph Path4 ["4. GitHub Textbook Translation"]
        direction LR
        Input4["Human: Enter Repo URL, Branch and Glossary"]

        subgraph Auto4 ["AUTOMATED GITHUB PIPELINE"]
            direction LR
            Clone4["Clone Source Read-Only (disabled-source-push)"]
            MergeGloss4["Merge 3-Tier Glossaries (General, SD, Course)"]

            subgraph VarAnalysis4 ["Variable Analysis (Gemini 3.5 Flash)"]
                direction TB
                SeedProtected4["Seed Protected Platform Identifiers (NODE_ENV, _id, process.env)"]
                GeminiVars4["Generate Portuguese Identifiers (Matching Convention)"]
                ValidateVars4["Deterministic Repo-Wide Collision and Delta Validation"]
                SeedProtected4 --> GeminiVars4 --> ValidateVars4
            end

            subgraph ProseTrans4 ["Prose Translation and Variable Replacement"]
                direction TB
                ProseBot4["MarkdownTranslationBot and HTMLTranslationAgent"]
                ApplyVars4["Apply Approved Variable Renames to Code and Linked IDs"]
                ProseBot4 --> ApplyVars4
            end

            SyntaxCheck4["Baseline-Aware Code Syntax Validation (Python Dedent)"]
            GHReport4["GitHubTranslationReportGenerator (Reviewing, Variables, Resources)"]
            Publish4["Create Personal Public Repo and Publish GitHub Pages"]

            Clone4 --> MergeGloss4 --> VarAnalysis4 --> ProseTrans4 --> SyntaxCheck4 --> GHReport4 --> Publish4
        end

        End4(((Publication Complete)))
        Input4 --> Clone4
        Publish4 --> End4
    end

    StartNode --> Input0
    StartNode --> Input1
    StartNode --> Input2
    StartNode --> Input3
    StartNode --> Input4

    class StartNode human
    class Input0 human
    class Input1 human
    class CseGlossSelect human
    class ManualImport1 human
    class Checklist1 human
    class Input2 human
    class Checklist2 human
    class Input3 human
    class Input4 human

    class CheckRemote auto
    class GitFetch auto
    class GitMerge auto
    class RestartApp auto
    class Extract1 auto
    class GroupCheck1 auto
    class LinkP_Pre1 auto
    class SpecialPages1 auto
    class Repack1 auto
    class Dash1 auto
    class AutoMigrate1 auto
    class Scrape2 auto
    class Piggyback2 auto
    class LinkP2 auto
    class ETReport2 auto
    class Inject2 auto
    class Verify2 auto
    class Extract3 auto
    class PairManifest auto
    class PairPath auto
    class LinksAudit3 auto
    class Sheet1 auto
    class Sheet2 auto
    class Sheet3 auto
    class End3 auto
    class Clone4 auto
    class MergeGloss4 auto
    class SyntaxCheck4 auto
    class GHReport4 auto
    class Publish4 auto
    class End4 auto

    class CsePrompt conditional
    class GroupDecision1 conditional
    class CheckpointCheck2 conditional

    class AuditGL1 bot
    class AuditSC1 bot
    class HTMLBot1 bot
    class XMLBot1 bot
    class TXTBot1 bot
    class OfficeBot1 bot
    class CSEPostPass1 bot
    class ETChunkBot bot
    class ETVerifyEN bot
    class PairAI bot
    class ContentAudit3 bot
    class SeedProtected4 bot
    class GeminiVars4 bot
    class ValidateVars4 bot
    class ProseBot4 bot
    class ApplyVars4 bot"""

new_content = re.sub(
    r"const graphText = `.*?`\.replace\(/\\r\\n/g, \'\\n\'\);",
    f"const graphText = `{graph_text}`.replace(/\\r\\n/g, '\\n');",
    content,
    flags=re.DOTALL,
)

with open("TranslationHUB_Flow_Final.html", "w", encoding="utf-8") as f:
    f.write(new_content)

print("done")
