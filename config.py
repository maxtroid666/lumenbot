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

# id основного командного чата (с темами/topics) - здесь работают напоминания и сводки
TEAM_CHAT_ID = int(os.getenv("TEAM_CHAT_ID", "-1004380656891"))

# через сколько минут тишины после "весомого" сообщения бот может сам напомнить о нём
SILENCE_INITIATIVE_MINUTES = int(os.getenv("SILENCE_INITIATIVE_MINUTES", "60"))

# сколько минут диалог считается "открытым" без повторного упоминания бота
DIALOGUE_TIMEOUT_MINUTES = int(os.getenv("DIALOGUE_TIMEOUT_MINUTES", "20"))

# час (по МСК) утренней и вечерней сводки в топике Люмена
DIGEST_MORNING_HOUR = int(os.getenv("DIGEST_MORNING_HOUR", "9"))
DIGEST_EVENING_HOUR = int(os.getenv("DIGEST_EVENING_HOUR", "21"))

# раз в сколько минут обновлять сквозную сводку по всему чату (для "периферийного зрения" бота)
GLOBAL_CONTEXT_UPDATE_MINUTES = int(os.getenv("GLOBAL_CONTEXT_UPDATE_MINUTES", "30"))
