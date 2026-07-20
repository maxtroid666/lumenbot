import os
from dotenv import load_dotenv

load_dotenv()

def _clean(value: str | None) -> str | None:
    """Убирает случайные пробелы/переносы строк, которые могли попасть при копипасте ключа."""
    return value.strip() if value else value


BOT_TOKEN = _clean(os.getenv("BOT_TOKEN"))
ANTHROPIC_API_KEY = _clean(os.getenv("ANTHROPIC_API_KEY"))
CLAUDE_MODEL = _clean(os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))

# шанс, что бот ответит сам по себе, без триггера (0 = отключено, никогда не пишет без повода)
RANDOM_REPLY_CHANCE = float(os.getenv("RANDOM_REPLY_CHANCE", "0"))

# слова-триггеры через запятую, при появлении которых бот включается в разговор
TRIGGER_WORDS = [
    w.strip().lower()
    for w in os.getenv("TRIGGER_WORDS", "бот,эй бот").split(",")
    if w.strip()
]

# сколько последних сообщений чата подтягивать в контекст
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "30"))

# путь к файлу базы данных SQLite (лёгкая встроенная БД без отдельного сервера)
DB_PATH = os.getenv("DB_PATH", "bot_memory.db")

# через сколько минут тишины после "весомого" сообщения бот может сам напомнить о нём
SILENCE_INITIATIVE_MINUTES = int(os.getenv("SILENCE_INITIATIVE_MINUTES", "60"))

# сколько минут диалог считается "открытым" без повторного упоминания бота
DIALOGUE_TIMEOUT_MINUTES = int(os.getenv("DIALOGUE_TIMEOUT_MINUTES", "15"))

# время (по МСК) утренней и вечерней сводки в топике Люмена
DIGEST_MORNING_HOUR = int(os.getenv("DIGEST_MORNING_HOUR", "10"))
DIGEST_MORNING_MINUTE = int(os.getenv("DIGEST_MORNING_MINUTE", "1"))
DIGEST_EVENING_HOUR = int(os.getenv("DIGEST_EVENING_HOUR", "21"))
DIGEST_EVENING_MINUTE = int(os.getenv("DIGEST_EVENING_MINUTE", "0"))

# раз в сколько минут обновлять сквозную сводку по всему чату (для "периферийного зрения" бота)
GLOBAL_CONTEXT_UPDATE_MINUTES = int(os.getenv("GLOBAL_CONTEXT_UPDATE_MINUTES", "30"))
