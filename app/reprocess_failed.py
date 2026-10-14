import os
import re
from controller import TranslationController


def _infer_translation_context(filepath):
    """Return the original workspace name and language from an output path."""
    normalized = os.path.normpath(filepath)
    match = re.search(
        r"(?:^|[\\/])(?P<name>[^\\/]+)_(?P<lang>PTBR|SPA)(?:[\\/]|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Could not infer the translated workspace and language from "
            f"{filepath!r}. Expected a directory ending in _PTBR or _SPA."
        )
    return match.group("name"), match.group("lang").upper()


def _failed_files_from_log(lines):
    """Extract final controller failures, with legacy XML-log compatibility."""
    retry_failures = []
    retry_succeeded = set()
    retry_outcomes_seen = False
    first_pass_failures = []
    legacy_xml_failures = []
    current_file = None
    failure_patterns = (
        (re.compile(r"Retry failed for (.*?\.(?:xml|qti)):\s", re.IGNORECASE), retry_failures),
        (
            re.compile(r"Translation failed for (.*?\.(?:xml|qti)):\s", re.IGNORECASE),
            first_pass_failures,
        ),
    )
    for line in lines:
        delegation = re.search(r"Delegating (.*?) to", line)
        if delegation:
            current_file = delegation.group(1)
        for pattern, collection in failure_patterns:
            match = pattern.search(line)
            if match and match.group(1) not in collection:
                collection.append(match.group(1))
                if collection is retry_failures:
                    retry_outcomes_seen = True
        retry_success = re.search(
            r"Retry succeeded for (.*?\.(?:xml|qti))(?:\s|$)",
            line,
            flags=re.IGNORECASE,
        )
        if retry_success:
            retry_outcomes_seen = True
            retry_succeeded.add(retry_success.group(1))
        if "XML Parse Error on attempt 3" in line and current_file:
            if current_file not in legacy_xml_failures:
                legacy_xml_failures.append(current_file)
    # Once sequential retry has run, only its explicit failures remain unresolved.
    if retry_outcomes_seen:
        return [path for path in retry_failures if path not in retry_succeeded]
    return first_pass_failures or legacy_xml_failures


def run():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(app_dir, "bots", "translation_log.txt")
    if not os.path.exists(log_path):
        print("No translation log found.")
        return

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    failed_files = _failed_files_from_log(lines)
                
    print(f"Found {len(failed_files)} unresolved XML/QTI file(s).")
    
    if not failed_files:
        return
        
    first_file = failed_files[0]
    try:
        input_dir, target_language = _infer_translation_context(first_file)
    except ValueError as error:
        print(error)
        return
        
    print(f"Initializing controller for {input_dir}")
    
    # Init controller. This will also create/copy the workspace if it didn't exist
    controller = TranslationController(target_language=target_language, input_dir=input_dir)
    
    # Reprocess only the failed files
    for file in failed_files:
        if os.path.exists(file):
            print(f"--- Reprocessing {file} ---")
            controller.process_file(file)
        else:
            print(f"File not found: {file}")
            
    print("All failed files reprocessed. Compressing back to IMSCC...")
    controller.workspace.compress_to_imscc(controller._log)
    print("Done!")

if __name__ == "__main__":
    run()
