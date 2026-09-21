import re

with open("TranslationHUB_Flow_Final.html", "r", encoding="utf-8") as f:
    content = f.read()

graph_text = r"""flowchart LR
    classDef human fill:#3d1a20,stroke:#ff6b81,stroke-width:2px,color:#ffd6dc
    classDef auto fill:#0f2d1e,stroke:#26de81,stroke-width:2px,color:#b8f5d8
    classDef bot fill:#2d2700,stroke:#ffd32a,stroke-width:2px,color:#fff4b8
    classDef conditional fill:#0e1f36,stroke:#45aaf2,stroke-width:2px,stroke-dasharray:5 5,color:#b8dcf8

    StartNode((Start Hub))

    subgraph Path1 ["1. Canvas IMSCC Translation"]
        direction LR
        Input1["Human: Select IMSCC"]

        subgraph Auto1 ["AUTOMATED HUB PROCESSING"]
            direction LR
            Extract["WorkspaceManager: Extract"]
            GroupCheck["Collect Group Configs<br/><small><i>(Canvas API)</i></small>"]
            LinkP_Pre["LinkProcessor: Pre-process global links"]

            subgraph FileLoop ["Parallel File Loop"]
                direction TB
                LinkP_Clean["LinkProcessor: Clean pre-translation links"]
                AuditGL["GlossaryAuditBot: Extract Terms"]
                AuditSC["ScriptureCheckBot: Extract Scriptures"]

                subgraph AITranslators ["AI Translation Bots (Route by Extension)"]
                    direction TB
                    HTMLBot["HTMLTranslationBot"]
                    XMLBot["XMLTranslationBot (XML and QTI)"]
                    TXTBot["TextTranslationBot"]
                end

                LinkP_Post["LinkProcessor: Rewrite church URLs"]

                LinkP_Clean --> AuditGL
                AuditGL --> AuditSC
                AuditSC --> HTMLBot
                AuditSC --> XMLBot
                AuditSC --> TXTBot
                HTMLBot --> LinkP_Post
                XMLBot --> LinkP_Post
                TXTBot --> LinkP_Post
            end

            Repack["WorkspaceManager: Repackage"]
            Dash1["DashboardGenerator"]

            Extract --> GroupCheck --> LinkP_Pre --> LinkP_Clean
            LinkP_Post --> Repack
            Repack --> Dash1
        end

        ManualImport["Human: Import to Canvas"]
        GroupDecision{"Has Groups?"}
        AutoMigrate["Canvas Group Migration<br/><small><i>(Canvas API)</i></small>"]
        Checklist1["Human: Review Checklist"]

        Input1 --> Extract
        Dash1 --> ManualImport
        ManualImport --> GroupDecision
        GroupDecision -- Yes --> AutoMigrate
        GroupDecision -- No --> Checklist1
        AutoMigrate --> Checklist1
    end

    subgraph Path2 ["2. EdTech Master Translator"]
        direction LR
        Input2["Human: Enter EdTech URL"]

        subgraph Auto2 ["AUTOMATED HUB PROCESSING"]
            direction LR
            ETLogin["Human: Google SSO Login (if needed)"]
            Scrape["EdTechScraperBot: Scrape"]

            subgraph EdTechLoop ["Parallel Page Loop"]
                direction TB
                ETAuditGL["GlossaryAuditBot: Extract Terms"]
                ETAuditSC["ScriptureCheckBot: Extract Scriptures"]
                ETHTMLBot["HTMLTranslationBot: Translate Pages"]
                ETAuditGL --> ETAuditSC --> ETHTMLBot
            end

            Inject["EdTechScraperBot: Inject"]
            ETLogin --> Scrape
            Scrape --> ETAuditGL
            ETHTMLBot --> Inject
        end

        Checklist2["Human: Review Checklist"]
        Input2 --> ETLogin
        Inject --> Checklist2
    end

    subgraph Path3 ["3. Quality Assurance Audit"]
        direction LR
        Input3["Human: Select IMSCCs"]

        subgraph Auto3 ["AUTOMATED QA AUDIT"]
            direction LR
            RunAudit["CourseAuditor: Cross-reference Files"]

            subgraph QALoop ["AI-Powered Audit"]
                direction TB
                Pairing["QAAuditBot: AI File Pairing"]
                ContentAudit["QAAuditBot: Content Audit"]
            end

            subgraph DetLoop ["Deterministic Audit"]
                direction TB
                LinksAudit["Links Audit: URL Comparison"]
            end

            subgraph QAReport ["Excel QA Report"]
                direction TB
                Sheet1["Page Audit Report"]
                Sheet2["Content Audit Report"]
                Sheet3["Links Audit Report"]
            end

            RunAudit --> Pairing
            RunAudit --> ContentAudit
            RunAudit --> LinksAudit
            Pairing --> Sheet1
            ContentAudit --> Sheet2
            LinksAudit --> Sheet3
        end

        End3(((Audit Complete)))
        Input3 --> RunAudit
        Sheet1 --> End3
        Sheet2 --> End3
        Sheet3 --> End3
    end

    StartNode --> Input1
    StartNode --> Input2
    StartNode --> Input3

    class StartNode human
    class Input1 human
    class ManualImport human
    class Checklist1 human
    class Input2 human
    class ETLogin human
    class Checklist2 human
    class Input3 human

    class Extract auto
    class GroupCheck auto
    class LinkP_Pre auto
    class LinkP_Clean auto
    class LinkP_Post auto
    class Repack auto
    class Dash1 auto
    class AutoMigrate auto
    class RunAudit auto
    class LinksAudit auto
    class Sheet1 auto
    class Sheet2 auto
    class Sheet3 auto

    class GroupDecision conditional

    class AuditGL bot
    class AuditSC bot
    class HTMLBot bot
    class XMLBot bot
    class TXTBot bot
    class Scrape bot
    class ETAuditGL bot
    class ETAuditSC bot
    class ETHTMLBot bot
    class Inject bot
    class Pairing bot
    class ContentAudit bot"""

new_content = re.sub(r'const graphText = `.*?`\.replace\(/\\r\\n/g, \'\\n\'\);', f'const graphText = `{graph_text}`.replace(/\\r\\n/g, \'\\n\');', content, flags=re.DOTALL)

# increase fonts
new_content = new_content.replace("font-size: 16px;", "font-size: 20px;")
new_content = new_content.replace("fontSize: '16px',", "fontSize: '20px',")

with open("TranslationHUB_Flow_Final.html", "w", encoding="utf-8") as f:
    f.write(new_content)

print("done")
