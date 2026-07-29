import os
from bots.scripturecheck_bot import ScriptureCheckBot

original_text = "And it came to pass that I, Nephi, said unto my father: I will go and do the things which the Lord hath commanded, for I know that the Lord giveth no commandments unto the children of men, save he shall prepare a way for them that they may accomplish the thing which he commandeth them. (1 Nephi 3:7)"

translated_text = "E ocorreu que eu, Néfi, falei para o meu pai: Eu vou e faço as coisas que Deus mandou, porque eu sei que Deus não dá mandamentos às pessoas sem arranjar um jeito para eles cumprirem o que ele mandou. (1 Néfi 3:7)"

print("--- Testing ScriptureCheckBot ---")
bot = ScriptureCheckBot(target_language="PTBR")
fixed = bot.process(translated_text, original_text)

print("\n--- ORIGINAL TRANSLATED ---")
print(translated_text)

print("\n--- FIXED TRANSLATED ---")
print(fixed)
