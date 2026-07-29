from bots.scripturecheck_bot import ScriptureCheckBot
bot = ScriptureCheckBot()
prompt = bot._extract_references.__code__.co_consts[2] # just grab prompt or redefine
original = "And it came to pass that I, Nephi, said unto my father: I will go and do the things which the Lord hath commanded, for I know that the Lord giveth no commandments unto the children of men, save he shall prepare a way for them that they may accomplish the thing which he commandeth them. (1 Nephi 3:7)"
# I'll just use the bot logic directly to see what it returns
from bots.api_utils import call_gemini_with_retry
prompt = (
    "Analyze the following text and identify all scripture references (e.g. 1 Nephi 3:7, D&C 8:2-3, Moses 1:39, Matthew 5:1).\n"
    "Output a JSON array of objects representing the references found.\n"
    "Only include references for the Book of Mormon, Doctrine and Covenants, and Pearl of Great Price. Do not include Bible references.\n\n"
    "Use this exact schema for each object:\n"
    "{\n"
    "  \"volume\": \"<bookofmormon | doctrineandcovenants | pearlofgreatprice>\",\n"
    "  \"book\": \"<slug>\",\n"
    "  \"chapter\": \"<chapter or section number>\",\n"
    "  \"verses\": [\"<verse_num_1>\", \"<verse_num_2>\"]\n"
    "}\n\n"
    "Acceptable slugs for bookofmormon:\n"
    "1-ne, 2-ne, jacob, enos, jarom, omni, w-of-m, mosiah, alma, hel, 3-ne, 4-ne, morm, ether, moro\n\n"
    "Acceptable slugs for doctrineandcovenants:\n"
    "Use \"dc\" for the book slug.\n\n"
    "Acceptable slugs for pearlofgreatprice:\n"
    "moses, abr, js-m, js-h, a-of-f\n\n"
    "If no references are found, return an empty array [].\n"
    "Output ONLY valid JSON. No markdown wrappers like ```json.\n\n"
    f"Text:\n{original}"
)
response = call_gemini_with_retry(bot.model, prompt, log_func=bot._log)
print("RAW Output:\n", response.text)
