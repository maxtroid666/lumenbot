import aiosqlite
from config import DB_PATH

# thread_id = 0 используем как "без темы" (обычный чат без Topics или General-тема)
NO_THREAD = 0


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL,          -- 'user' или 'assistant'
                author TEXT,                 -- имя человека, если role='user'
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_thread ON messages (chat_id, thread_id)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS summary_state (
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT 0,
                last_message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        await db.commit()


async def save_message(
    chat_id: int,
    role: str,
    content: str,
    author: str | None = None,
    thread_id: int = NO_THREAD,
) -> int:
    """Сохраняет сообщение и возвращает его id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO messages (chat_id, thread_id, role, author, content) VALUES (?, ?, ?, ?, ?)",
            (chat_id, thread_id, role, author, content),
        )
        await db.commit()
        return cursor.lastrowid


async def get_history(chat_id: int, thread_id: int, limit: int):
    """Последние `limit` сообщений конкретной темы чата, в хронологическом порядке."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT role, author, content FROM messages
            WHERE chat_id = ? AND thread_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (chat_id, thread_id, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed(rows))


async def get_last_summary_id(chat_id: int, thread_id: int) -> int:
    """Id последнего сообщения темы, вошедшего в предыдущее саммари. 0, если саммари ещё не делали."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_message_id FROM summary_state WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def set_last_summary_id(chat_id: int, thread_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO summary_state (chat_id, thread_id, last_message_id) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, thread_id) DO UPDATE SET last_message_id = excluded.last_message_id
            """,
            (chat_id, thread_id, message_id),
        )
        await db.commit()


async def get_messages_since(chat_id: int, thread_id: int, since_id: int, max_messages: int = 400):
    """Все сообщения темы с id > since_id, в хронологическом порядке (с ограничением сверху)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, role, author, content FROM messages
            WHERE chat_id = ? AND thread_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (chat_id, thread_id, since_id, max_messages),
        )
        return await cursor.fetchall()


async def get_latest_message_id(chat_id: int, thread_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT MAX(id) FROM messages WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else 0
