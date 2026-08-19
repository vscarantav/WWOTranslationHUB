import os
import glob
import re

dir_path = r"c:\Users\vscaran\Desktop\DevProjects\WWOTranslationHUB\edtech_workspace\raw_html_PTBR"

count = 0
for filepath in glob.glob(os.path.join(dir_path, "*.html")):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    original = content
    content = re.sub(r"^```html\s*?\n", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\n```\s*?$", "", content)
    content = content.strip()
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        count += 1
        print(f"Cleaned {os.path.basename(filepath)}")

print(f"Fixed {count} files with leaked markdown backticks.")
