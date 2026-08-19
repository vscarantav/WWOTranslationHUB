import sys
import os
import json

# Add app dir to path to find our modules
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from bots.edtech_bot import EdTechScraperBot

def main():
    print("Testing Injection Phase Directly...")
    workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edtech_workspace")
    bot = EdTechScraperBot(
        book_url="https://books.byui.edu/somthingelse",
        target_language="PTBR",
        workspace_dir=workspace,
        print_callback=print
    )
    
    bot.run_injection()
    print("Injection phase completed!")

if __name__ == "__main__":
    main()
