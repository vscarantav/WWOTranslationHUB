import os
from dotenv import load_dotenv
load_dotenv()
from app.bots.html_bot import HTMLTranslationBot

input_file = r"C:\Users\vscaran\Desktop\DevProjects\WWOTranslationHUB\test_run\course_extract\wiki_content\setup-notes-and-course-settings.html"
with open(input_file, "r", encoding="utf-8") as f:
    html_content = f.read()

print("Running HTMLTranslationBot with the custom setup notes prompt on the real file...")

bot = HTMLTranslationBot(target_language="PTBR")

custom_prompt = (
    "You are an expert HTML translator. For this specific 'setup notes' page, you must translate ONLY the text inside the table cells (<td> and <th> tags). "
    "Do NOT translate any headers, titles, or paragraphs outside the tables. "
    "Furthermore, instead of replacing the English text in the table cells, you must APPEND the PTBR translation after the English text, separated by ' / ' (e.g., 'Modules / Módulos', 'Due / Prazo de entrega: Day/Dia', 'Available From / Disponível a partir de: N/A'). "
    "Keep 'N/A' as is, and translate variables like 'Day' to 'Dia' etc. "
    "Do not modify tags or layout. Output strictly the HTML block."
)
bot.set_system_prompt(custom_prompt)

translated_content = bot.translate_html_content(html_content, page_title="Setup Notes")

output_file = "test_run/translated-setup-notes-real.html"
with open(output_file, "w", encoding="utf-8") as f:
    f.write(translated_content)

print(f"Done! Saved translated output to {output_file}")
