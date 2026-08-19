import sys
import os
import json

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))
from bots.edtech_bot import EdTechScraperBot

def main():
    print("Injecting missing lessons 7 and 12...")
    workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edtech_workspace")
    bot = EdTechScraperBot(
        book_url="https://books.byui.edu/somthingelse",
        target_language="PTBR",
        workspace_dir=workspace,
        print_callback=print
    )
    
    # Temporarily override the mapping file reader
    original_run_injection = bot.run_injection
    
    mapping_file = os.path.join(workspace, "edtech_mapping.json")
    with open(mapping_file, 'r', encoding='utf-8') as f:
        extracted_files = json.load(f)
        
    # Filter for only lesson 7 and lesson 12
    filtered_files = [f for f in extracted_files if f['filename'] in ['lesson_7.html', 'lesson_12.html']]
    
    # Overwrite the json temporarily for this run
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(filtered_files, f, indent=4)
        
    try:
        # Run the injection, which will now only read the filtered file
        bot.run_injection()
    finally:
        # Restore the full json
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_files, f, indent=4)
            
    print("Finished injecting missing lessons!")

if __name__ == "__main__":
    main()
