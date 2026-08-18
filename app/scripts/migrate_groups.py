import os
import sys
import argparse
import json
import requests
from dotenv import load_dotenv

# Add parent dir to path to import bots
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bots.txt_bot import TextTranslationBot

def get_source_credentials():
    url = os.getenv("CANVAS_API_URL")
    token = os.getenv("CANVAS_API_TOKEN")
    if not url or not token:
        raise ValueError("CANVAS_API_URL or CANVAS_API_TOKEN is not set in .env")
    return url.rstrip('/'), token

def fetch_paginated(url, token):
    results = []
    headers = {"Authorization": f"Bearer {token}"}
    if '?' in url:
        url += "&per_page=100"
    else:
        url += "?per_page=100"
        
    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        results.extend(response.json())
        
        url = None
        if 'Link' in response.headers:
            links = response.headers['Link'].split(',')
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find('<')+1:link.find('>')]
                    break
    return results

def fetch_group_categories(course_id, base_url, token):
    url = f"{base_url}/api/v1/courses/{course_id}/group_categories"
    return fetch_paginated(url, token)

def fetch_groups(category_id, base_url, token):
    url = f"{base_url}/api/v1/group_categories/{category_id}/groups"
    return fetch_paginated(url, token)

def create_group_category(course_id, name, base_url, token):
    url = f"{base_url}/api/v1/courses/{course_id}/group_categories"
    response = requests.post(url, headers={"Authorization": f"Bearer {token}"}, data={"name": name})
    response.raise_for_status()
    return response.json()

def create_group(category_id, name, base_url, token):
    url = f"{base_url}/api/v1/group_categories/{category_id}/groups"
    response = requests.post(url, headers={"Authorization": f"Bearer {token}"}, data={"name": name})
    response.raise_for_status()
    return response.json()

def check_course_has_groups(course_id):
    """Utility function for the UI to quickly check if a course has groups."""
    try:
        url, token = get_source_credentials()
        categories = fetch_group_categories(course_id, url, token)
        return len(categories) > 0
    except Exception as e:
        print(f"[GroupMigrator] Error checking for groups in {course_id}: {e}")
        return False

def run_migration(source_id, target_id, lang, log_func, target_domain=None, target_token=None):
    log_func(f"[GroupMigrator] Initializing TextTranslationBot for {lang}...")
    translator = TextTranslationBot(target_language=lang)

    source_url, source_token = get_source_credentials()

    log_func(f"[GroupMigrator] Fetching group categories for source course {source_id}...")
    try:
        categories = fetch_group_categories(source_id, source_url, source_token)
    except Exception as e:
        log_func(f"[GroupMigrator] Failed to fetch group categories: {e}")
        return

    if not categories:
        log_func("[GroupMigrator] No groups found in the English course. Skipping Canvas API migration.")
        return
    
    export_data = []

    for cat in categories:
        cat_name = cat['name']
        log_func(f"[GroupMigrator] Found Category: {cat_name}")
        translated_cat_name = translator.translate_txt_content(cat_name)
        log_func(f"[GroupMigrator]   -> Translated: {translated_cat_name}")
        
        try:
            groups = fetch_groups(cat['id'], source_url, source_token)
        except Exception as e:
            log_func(f"[GroupMigrator] Failed to fetch groups for category {cat['id']}: {e}")
            continue

        translated_groups = []
        for g in groups:
            g_name = g['name']
            translated_g_name = translator.translate_txt_content(g_name)
            log_func(f"[GroupMigrator]     Group: {g_name} -> {translated_g_name}")
            translated_groups.append({"original": g_name, "translated": translated_g_name})
            
        export_data.append({
            "category_original": cat_name,
            "category_translated": translated_cat_name,
            "groups": translated_groups
        })

    # Save export to Reports/ directory to keep hub root clean
    hub_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reports_dir = os.path.join(hub_dir, "Reports")
    os.makedirs(reports_dir, exist_ok=True)
    export_file = os.path.join(reports_dir, f"groups_export_{source_id}_{lang}.json")
    try:
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=4, ensure_ascii=False)
        log_func(f"[GroupMigrator] Saved translated group structure to {export_file}")
    except Exception as e:
        log_func(f"[GroupMigrator] Failed to save export file: {e}")

    if target_id:
        log_func(f"[GroupMigrator] Target course {target_id} provided. Creating groups via API...")
        
        t_url = source_url
        t_token = source_token
        
        if target_domain:
            if not target_domain.startswith("http"):
                target_domain = f"https://{target_domain}"
            t_url = target_domain.rstrip('/')
            
        if target_token:
            t_token = target_token
            
        if t_url != source_url and not target_token:
            log_func("[GroupMigrator] WARNING: You provided a target domain but no target token. The script will try to use the source token, but it might fail if the instances use different developer keys.")

        for cat_data in export_data:
            log_func(f"[GroupMigrator] Creating Category: {cat_data['category_translated']}...")
            try:
                new_cat = create_group_category(target_id, cat_data['category_translated'], t_url, t_token)
                for g_data in cat_data['groups']:
                    log_func(f"[GroupMigrator]   Creating Group: {g_data['translated']}...")
                    create_group(new_cat['id'], g_data['translated'], t_url, t_token)
            except Exception as e:
                log_func(f"[GroupMigrator] Error creating group structure: {e}")
                
        log_func("[GroupMigrator] Migration complete!")
    else:
        log_func("[GroupMigrator] No target course provided. Run again with --target to create the groups in Canvas.")

def main():
    parser = argparse.ArgumentParser(description="Migrate and Translate Canvas Groups")
    parser.add_argument("--source", required=True, help="Source Course ID")
    parser.add_argument("--target", required=False, help="Target Course ID (if known)")
    parser.add_argument("--lang", default="PTBR", help="Target Language for translation")
    parser.add_argument("--target-domain", required=False, help="Target Canvas domain if different from source (e.g. byui.instructure.com)")
    parser.add_argument("--target-token", required=False, help="Target Canvas API token if different from source")
    args = parser.parse_args()

    # Load environment variables
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
    load_dotenv(env_path)

    run_migration(args.source, args.target, args.lang, print, args.target_domain, args.target_token)

if __name__ == "__main__":
    main()
