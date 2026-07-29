import os
import re
from controller import TranslationController

def run():
    log_path = "translation_log.txt"
    if not os.path.exists(log_path):
        print("No translation log found.")
        return

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    failed_files = []
    current_file = None

    for line in lines:
        if "Delegating" in line:
            m = re.search(r"Delegating (.*?) to", line)
            if m:
                current_file = m.group(1)
        elif "JSON Error on attempt 3" in line and current_file:
            if current_file not in failed_files:
                failed_files.append(current_file)
                
    print(f"Found {len(failed_files)} files that failed on attempt 3.")
    
    if not failed_files:
        return
        
    # Initialize controller for PTBR. We can infer the input_dir from the file path.
    # Typical path: .../BUS116starting-a-business-english-master-export_PTBR/g...
    # We extract 'BUS116starting-a-business-english-master-export'
    first_file = failed_files[0]
    match = re.search(r"/(.*?_export)_PTBR/", first_file)
    if match:
        input_dir = match.group(1)
    else:
        input_dir = "BUS116starting-a-business-english-master-export"
        
    print(f"Initializing controller for {input_dir}")
    
    # Init controller. This will also create/copy the workspace if it didn't exist
    controller = TranslationController(target_language="PTBR", input_dir=input_dir)
    
    # Reprocess only the failed files
    for file in failed_files:
        if os.path.exists(file):
            print(f"--- Reprocessing {file} ---")
            controller.process_file(file)
        else:
            print(f"File not found: {file}")
            
    print("All failed files reprocessed. Compressing back to IMSCC...")
    controller.compress_to_imscc()
    print("Done!")

if __name__ == "__main__":
    run()
