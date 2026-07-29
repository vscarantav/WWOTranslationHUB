import os
from bots.scripturecheck_bot import ScriptureCheckBot
from bots.auditor_bot import GlossaryAuditBot

original_text = "And it came to pass that I, Nephi, said unto my father: I will go and do the things which the Lord hath commanded, for I know that the Lord giveth no commandments unto the children of men, save he shall prepare a way for them that they may accomplish the thing which he commandeth them. (1 Nephi 3:7). Please consult your Academic Advisor."

print("--- Testing ScriptureCheckBot ---")
scripture_bot = ScriptureCheckBot(target_language="PTBR")
scriptures = scripture_bot.get_scriptures_for_text(original_text)
print(f"Scriptures: {scriptures}")

print("\n--- Testing GlossaryAuditBot ---")
auditor_bot = GlossaryAuditBot(target_language="PTBR")
terms = auditor_bot.get_relevant_terms(original_text)
print(f"Terms: {terms}")
