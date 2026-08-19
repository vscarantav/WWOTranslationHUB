import os
import json
import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

class EdTechScraperBot:
    def __init__(self, book_url, target_language, workspace_dir, print_callback=print):
        self.book_url = book_url
        self.target_language = target_language
        self.workspace_dir = workspace_dir
        self.print_callback = print_callback
        self.base_url = "https://books.byui.edu"
        
        # Ensure workspace dirs exist
        self.raw_dir = os.path.join(self.workspace_dir, "raw_html")
        # Let the TranslationController create the translated directory and copy files
        self.translated_dir = os.path.join(self.workspace_dir, f"raw_html_{self.target_language}")
        os.makedirs(self.raw_dir, exist_ok=True)

    def _ensure_login(self, page):
        """Ensures the user is logged in by navigating to the base URL and checking the login button."""
        self.print_callback(f"Navigating to base URL for login check: {self.base_url}")
        page.goto(self.base_url, timeout=60000)
        
        # Give the website 3 seconds to verify the session and replace the login button with the user profile
        time.sleep(3)
        
        login_selector = 'button#user-link[data-target-template="modal-login"]'
        logged_in_selector = 'button#user-link[data-bs-toggle="dropdown"]'
        
        needs_login = False
        if page.locator(login_selector).is_visible():
            needs_login = True
        
        if needs_login:
            self.print_callback("Login button detected. Initiating Google Login flow...")
            try:
                # Click the user link
                page.click(login_selector)
                
                # Wait for Google login button in modal
                google_btn_selector = 'button[data-action="LoginGoogle"]'
                try:
                    page.wait_for_selector(google_btn_selector, timeout=5000, state="visible")
                    page.click(google_btn_selector)
                except:
                    self.print_callback("Modal animation issue or hidden button. Forcing click on Google Login...")
                    # Force click it via JS in case it's in the DOM but Playwright thinks it's hidden
                    page.evaluate(f'document.querySelector(`{google_btn_selector}`).click()')
                
                self.print_callback("Please complete the Google SSO login in the browser...")
                self.print_callback("Waiting for redirect back to the homepage...")
                
                # Wait for the initial redirect to happen (either to an auth endpoint or to Google)
                try:
                    # Wait until the URL is definitely NOT the base URL anymore
                    page.wait_for_function('!window.location.href.endsWith("books.byui.edu/") && !window.location.href.endsWith("books.byui.edu")', timeout=10000)
                except Exception as e:
                    self.print_callback("Did not detect immediate URL change, waiting anyway...")
                
                # Now that we are off the homepage (on the SSO page), wait until we return to books.byui.edu
                # The user can take up to 3 minutes to type their password.
                page.wait_for_function('window.location.href.endsWith("books.byui.edu/") || window.location.href.endsWith("books.byui.edu")', timeout=180000)
                
                # Wait a moment for the post-login homepage to fully render
                time.sleep(3)
                self.print_callback("Login confirmed! Proceeding...")
            except Exception as e:
                self.print_callback(f"Timed out or error during login flow: {e}. The script will try to proceed anyway.")
        else:
            self.print_callback("Already logged in.")

    def run_extraction(self):
        """Extracts all HTML from the book lessons."""
        extracted_files = []
        self.print_callback(f"Starting Playwright for EdTech extraction...")
        
        user_data_dir = os.path.join(os.path.dirname(__file__), "playwright_profile")
        
        with sync_playwright() as p:
            self.print_callback("Launching browser. Please log in if prompted...")
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False, 
                no_viewport=True
            )
            
            page = browser.new_page()
            
            # Ensure logged in before navigating to the specific book URL
            self._ensure_login(page)
            
            self.print_callback(f"Navigating to Book TOC: {self.book_url}")
            page.goto(self.book_url, timeout=60000)
            
            try:
                page.wait_for_selector('div#toc', timeout=10000)
            except:
                self.print_callback("TOC not found immediately. Waiting...")
                page.wait_for_selector('div#toc', timeout=60000)

            self.print_callback("Parsing Table of Contents...")
            
            # Use specific hierarchy from HTML snippets: .toc-row with data-entity-type="chapter" 
            # where data-children="" (meaning no sub-chapters/lessons inside it)
            locators = page.locator('div.toc-row[data-entity-type="chapter"][data-children=""] > a.btn.text-start').all()
            
            lesson_urls = []
            for loc in locators:
                href = loc.get_attribute('href')
                if href:
                    lesson_urls.append(urljoin(self.book_url, href))
            
            self.print_callback(f"Found {len(lesson_urls)} lessons to extract.")
            
            for index, url in enumerate(lesson_urls):
                self.print_callback(f"Extracting [{index+1}/{len(lesson_urls)}]: {url}")
                page.goto(url)
                
                # 1. Click "Edit"
                try:
                    page.wait_for_selector('button[data-action="ToggleEditor"]', timeout=10000)
                    page.click('button[data-action="ToggleEditor"]')
                except:
                    self.print_callback(f"Could not find Edit button on {url}. Skipping.")
                    continue
                
                # 2. Click "Edit HTML"
                try:
                    page.wait_for_selector('button.bi-code[data-target="#editor-tray-code-box"]', timeout=5000)
                    page.click('button.bi-code[data-target="#editor-tray-code-box"]')
                except:
                    self.print_callback(f"Could not find Edit HTML button on {url}. Skipping.")
                    continue
                
                # 3. Extract HTML from code-box
                try:
                    page.wait_for_selector('div#code-box', timeout=5000)
                    html_content = page.evaluate('document.getElementById("code-box").innerText')
                    
                    # Extract the page title
                    title_text = page.evaluate('document.getElementById("chapter-title") ? document.getElementById("chapter-title").innerText : ""')
                    if title_text:
                        # Prepend it as a hidden tag so the TranslationController automatically translates it
                        html_content = f'<div id="edtech-meta-title" style="display:none;">{title_text}</div>\n' + html_content
                    
                    filename = f"lesson_{index+1}.html"
                    filepath = os.path.join(self.raw_dir, filename)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    
                    extracted_files.append({
                        "url": url,
                        "filename": filename,
                        "raw_filepath": filepath,
                        "translated_filepath": os.path.join(self.translated_dir, filename)
                    })
                except Exception as e:
                    self.print_callback(f"Error extracting HTML on {url}: {e}")
                    
            browser.close()
            
            with open(os.path.join(self.workspace_dir, "edtech_mapping.json"), 'w', encoding='utf-8') as f:
                json.dump(extracted_files, f, indent=4)
                
        return extracted_files

    def run_injection(self):
        """Injects translated HTML back into the book lessons."""
        self.print_callback(f"Starting Playwright for EdTech injection...")
        
        mapping_file = os.path.join(self.workspace_dir, "edtech_mapping.json")
        if not os.path.exists(mapping_file):
            self.print_callback("Mapping file not found. Cannot inject.")
            return
            
        with open(mapping_file, 'r', encoding='utf-8') as f:
            extracted_files = json.load(f)
            
        user_data_dir = os.path.join(os.path.dirname(__file__), "playwright_profile")
        
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                no_viewport=True
            )
            page = browser.new_page()
            
            # Ensure logged in before injection
            self._ensure_login(page)
            
            for item in extracted_files:
                url = item['url']
                translated_path = item['translated_filepath']
                
                if not os.path.exists(translated_path):
                    self.print_callback(f"Translated file not found for {url}, skipping.")
                    continue
                    
                with open(translated_path, 'r', encoding='utf-8') as f:
                    translated_html = f.read()
                
                # Parse out the piggybacked title
                import re
                match = re.search(r'<div id="edtech-meta-title"[^>]*>(.*?)</div>', translated_html, flags=re.IGNORECASE | re.DOTALL)
                translated_title = None
                if match:
                    translated_title = match.group(1).strip()
                    translated_html = translated_html[:match.start()] + translated_html[match.end():]
                    translated_html = translated_html.strip()
                
                self.print_callback(f"Injecting into: {url}")
                page.goto(url)
                
                # 1. Click "Edit"
                try:
                    page.wait_for_selector('button[data-action="ToggleEditor"]', timeout=20000)
                    page.click('button[data-action="ToggleEditor"]')
                except:
                    self.print_callback(f"Could not find Edit button on {url}. Skipping.")
                    continue
                
                # 2. Click "Edit HTML"
                try:
                    page.wait_for_selector('button.bi-code[data-target="#editor-tray-code-box"]', timeout=5000)
                    page.click('button.bi-code[data-target="#editor-tray-code-box"]')
                except:
                    self.print_callback(f"Could not find Edit HTML button on {url}. Skipping.")
                    continue
                
                # 3. Inject translated HTML
                try:
                    page.wait_for_selector('div#code-box', timeout=5000)
                    page.evaluate(f'''(htmlContent) => {{
                        const box = document.getElementById("code-box");
                        box.innerText = htmlContent;
                        box.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}''', translated_html)
                    
                    # Inject translated title
                    if translated_title:
                        page.evaluate(f'''(title) => {{
                            const el = document.getElementById("chapter-title");
                            if (el) {{
                                el.innerText = title;
                                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            }}
                        }}''', translated_title)
                        self.print_callback(f"Injected translated title: {translated_title}")
                    
                    # 4. Click Apply
                    try:
                        page.wait_for_selector('button[data-custom-action="ApplyCode"]', timeout=5000)
                        page.click('button[data-custom-action="ApplyCode"]')
                        self.print_callback("Clicked Apply button.")
                    except:
                        self.print_callback("Could not find Apply button. It might have applied automatically.")
                        
                    # Wait 2 seconds between clicks as requested
                    time.sleep(2)
                    
                    # 5. Click Save
                    try:
                        page.wait_for_selector('button[data-ribbon-action="Save"]', timeout=5000)
                        page.click('button[data-ribbon-action="Save"]')
                        self.print_callback("Clicked Save button.")
                        time.sleep(2) # Brief wait after saving before moving to next page
                    except:
                        self.print_callback("Could NOT find the Save button. Please click Save manually within 15 seconds.")
                        page.wait_for_timeout(15000)
                        
                except Exception as e:
                    self.print_callback(f"Error injecting HTML on {url}: {e}")
                    
            browser.close()
            self.print_callback("Injection complete.")
