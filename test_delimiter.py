import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

model = genai.GenerativeModel("gemini-3.5-flash")

system_prompt = "You are an expert academic text translator. Translate the given text values to PTBR. Maintain any HTML tags within the strings exactly as they are. Do not translate URLs or filenames. The input and output format is custom: each item starts with '[[[ID]]]' followed by the text. Return exactly the same format with the same IDs."

batch = {"0": "Please <a href=\"link\">click here</a> to proceed.", "1": "Another string with \"quotes\"."}

input_text = ""
for k, v in batch.items():
    input_text += f"[[[{k}]]]\n{v}\n"

full_prompt = f"System Instructions:\n{system_prompt}\n\nContent:\n{input_text}"

response = model.generate_content(full_prompt)
print("RAW OUTPUT:\n", response.text)
