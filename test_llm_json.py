import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

model = genai.GenerativeModel(
    "gemini-3.5-flash",
    generation_config={"response_mime_type": "application/json"}
)

system_prompt = "You are an expert academic text translator. Translate the given JSON string values to PTBR. Maintain any HTML tags within the strings exactly as they are. Do not translate URLs or filenames. Return a JSON object with the exact same keys."

batch = {"0": "S05 Aplicar"}
full_prompt = f"System Instructions:\n{system_prompt}\n\nContent:\n{json.dumps(batch, ensure_ascii=False)}"

response = model.generate_content(full_prompt)
print("RAW TEXT:\n", response.text)
try:
    print("PARSED:", json.loads(response.text))
except Exception as e:
    print("JSON Error:", e)
