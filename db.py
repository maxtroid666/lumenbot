import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,          -- 'user' или 'assistant'
                author TEXT,                 -- имя человека, если role='user'
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_id ON messages (chat_id)"
        )
        await db.commit()


async def save_message(chat_id: int, role: str, content: str, author: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (chat_id, role, author, content) VALUES (?, ?, ?, ?)",
            (chat_id, role, author, content),
        )
        await db.commit()


async def get_history(chat_id: int, limit: int):
    """Возвращает последние `limit` сообщений чата в хронологическом порядке."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT role, author, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed(rows))
