import os
from dotenv import load_dotenv

load_dotenv()

def _clean(value: str | None) -> str | None:
    """Убирает случайные пробелы/переносы строк, которые могли попасть при копипасте ключа."""
    return value.strip() if value else value


BOT_TOKEN = _clean(os.getenv("BOT_TOKEN"))
YANDEX_API_KEY = _clean(os.getenv("YANDEX_API_KEY"))
YANDEX_FOLDER_ID = _clean(os.getenv("YANDEX_FOLDER_ID"))
YANDEX_MODEL = _clean(os.getenv("YANDEX_MODEL", "yandexgpt/latest"))

# шанс, что бот ответит сам по себе, без триггера (0.03 = 3%)
RANDOM_REPLY_CHANCE = float(os.getenv("RANDOM_REPLY_CHANCE", "0.03"))

# слова-триггеры через запятую, при появлении которых бот включается в разговор
TRIGGER_WORDS = [
    w.strip().lower()
    for w in os.getenv("TRIGGER_WORDS", "бот,эй бот").split(",")
    if w.strip()
]

# сколько последних сообщений чата подтягивать в контекст для Claude
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "30"))

# путь к файлу базы данных SQLite (лёгкая встроенная БД без отдельного сервера)
DB_PATH = os.getenv("DB_PATH", "bot_memory.db")
