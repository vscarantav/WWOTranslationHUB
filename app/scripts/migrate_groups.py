import os
import sys
import argparse
import json
import requests
from dotenv import load_dotenv

# Add parent dir to path to import bots
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bots.txt_bot import TextTranslationBot

def get_canvas_headers():
    token = os.getenv("CANVAS_API_TOKEN")
    if not token:
        raise ValueError("CANVAS_API_TOKEN is not set in .env")
    return {"Authorization": f"Bearer {token}"}

def get_base_url():
    url = os.getenv("CANVAS_API_URL")
    if not url:
        raise ValueError("CANVAS_API_URL is not set in .env")
    return url.rstrip('/')

def fetch_group_categories(course_id):
    url = f"{get_base_url()}/api/v1/courses/{course_id}/group_categories"
    response = requests.get(url, headers=get_canvas_headers())
    response.raise_for_status()
    return response.json()

def fetch_groups(category_id):
    url = f"{get_base_url()}/api/v1/group_categories/{category_id}/groups"
    response = requests.get(url, headers=get_canvas_headers())
    response.raise_for_status()
    return response.json()

def create_group_category(course_id, name):
    url = f"{get_base_url()}/api/v1/courses/{course_id}/group_categories"
    response = requests.post(url, headers=get_canvas_headers(), data={"name": name})
    response.raise_for_status()
    return response.json()

def create_group(category_id, name):
    url = f"{get_base_url()}/api/v1/group_categories/{category_id}/groups"
    response = requests.post(url, headers=get_canvas_headers(), data={"name": name})
    response.raise_for_status()
    return response.json()

def run_migration(source_id, target_id, lang, log_func):
    log_func(f"[GroupMigrator] Initializing TextTranslationBot for {lang}...")
    translator = TextTranslationBot(target_language=lang)

    log_func(f"[GroupMigrator] Fetching group categories for source course {source_id}...")
    try:
        categories = fetch_group_categories(source_id)
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
            groups = fetch_groups(cat['id'])
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

    export_file = f"groups_export_{source_id}_{lang}.json"
    try:
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=4, ensure_ascii=False)
        log_func(f"[GroupMigrator] Saved translated group structure to {export_file}")
    except Exception as e:
        log_func(f"[GroupMigrator] Failed to save export file: {e}")

    if target_id:
        log_func(f"[GroupMigrator] Target course {target_id} provided. Creating groups via API...")
        for cat_data in export_data:
            log_func(f"[GroupMigrator] Creating Category: {cat_data['category_translated']}...")
            try:
                new_cat = create_group_category(target_id, cat_data['category_translated'])
                for g_data in cat_data['groups']:
                    log_func(f"[GroupMigrator]   Creating Group: {g_data['translated']}...")
                    create_group(new_cat['id'], g_data['translated'])
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
    args = parser.parse_args()

    # Load environment variables
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
    load_dotenv(env_path)

    run_migration(args.source, args.target, args.lang, print)

if __name__ == "__main__":
    main()
