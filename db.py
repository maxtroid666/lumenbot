import aiosqlite
from config import DB_PATH
from topics import SEED_CHAT_ID, SEED_TOPICS, SEED_DIGEST_THREAD_ID

# thread_id = 0 используем как "без темы" (обычный чат без Topics или General-тема)
NO_THREAD = 0


async def _ensure_column(db, table: str, column: str, ddl: str):
    """Проверяет реальные колонки таблицы через PRAGMA и добавляет недостающую."""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in await cursor.fetchall()]
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def _migrate_summary_state(db):
    """summary_state раньше был с PRIMARY KEY(chat_id) без thread_id - пересобираем под новую схему."""
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='summary_state'"
    )
    exists = await cursor.fetchone()
    if not exists:
        return

    cursor = await db.execute("PRAGMA table_info(summary_state)")
    cols = [row[1] for row in await cursor.fetchall()]
    if "thread_id" in cols:
        return  # уже новая схема

    await db.execute("ALTER TABLE summary_state RENAME TO summary_state_old")
    await db.execute(
        """
        CREATE TABLE summary_state (
            chat_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL DEFAULT 0,
            last_message_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, thread_id)
        )
        """
    )
    await db.execute(
        """
        INSERT INTO summary_state (chat_id, thread_id, last_message_id)
        SELECT chat_id, 0, last_message_id FROM summary_state_old
        """
    )
    await db.execute("DROP TABLE summary_state_old")


async def _seed_default_topics(db):
    """Одноразовая миграция: переносит захардкоженные темы старого чата команды в базу,
    чтобы после обновления бота не пришлось настраивать /setup заново вручную."""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM topic_info WHERE chat_id = ?", (SEED_CHAT_ID,)
    )
    row = await cursor.fetchone()
    if row and row[0] > 0:
        return  # уже настроено - либо этим же сидом раньше, либо вручную через /setup

    for thread_id, info in SEED_TOPICS.items():
        await db.execute(
            "INSERT OR IGNORE INTO topic_info (chat_id, thread_id, name, focus) VALUES (?, ?, ?, ?)",
            (SEED_CHAT_ID, thread_id, info["name"], info.get("focus", "")),
        )
    await db.execute(
        """
        INSERT INTO chat_settings (chat_id, digest_thread_id) VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET digest_thread_id = excluded.digest_thread_id
        """,
        (SEED_CHAT_ID, SEED_DIGEST_THREAD_ID),
    )
    await db.execute("INSERT OR IGNORE INTO known_chats (chat_id) VALUES (?)", (SEED_CHAT_ID,))


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
        # миграция старой базы новыми колонками - проверяем реальные колонки, а не гадаем try/except
        await _ensure_column(db, "messages", "thread_id", "thread_id INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "messages", "telegram_user_id", "telegram_user_id INTEGER")
        await _ensure_column(db, "messages", "needs_followup", "needs_followup INTEGER NOT NULL DEFAULT 0")
        await _ensure_column(db, "messages", "followup_done", "followup_done INTEGER NOT NULL DEFAULT 0")

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_thread ON messages (chat_id, thread_id)"
        )

        await _migrate_summary_state(db)
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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS dialogue_state (
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS digest_progress (
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT 0,
                last_message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS global_context (
                chat_id INTEGER PRIMARY KEY,
                summary TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS context_progress (
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT 0,
                last_message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS digest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                kind TEXT NOT NULL,       -- 'morning' или 'evening'
                sent_date TEXT NOT NULL,  -- 'YYYY-MM-DD'
                UNIQUE(chat_id, kind, sent_date)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_info (
                chat_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                focus TEXT,
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                digest_thread_id INTEGER
            )
            """
        )
        await _seed_default_topics(db)
        await db.commit()


async def save_message(
    chat_id: int,
    role: str,
    content: str,
    author: str | None = None,
    thread_id: int = NO_THREAD,
    telegram_user_id: int | None = None,
    needs_followup: bool = False,
) -> int:
    """Сохраняет сообщение и возвращает его id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages (chat_id, thread_id, role, author, content, telegram_user_id, needs_followup)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, thread_id, role, author, content, telegram_user_id, int(needs_followup)),
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


# ---------- диалоговое состояние (продолжение без повтора имени) ----------

async def get_active_dialogue(chat_id: int, thread_id: int, timeout_minutes: int) -> int | None:
    """Возвращает user_id, с кем открыт диалог, если он не протух по таймауту."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"""
            SELECT user_id FROM dialogue_state
            WHERE chat_id = ? AND thread_id = ?
            AND updated_at >= datetime('now', '-{int(timeout_minutes)} minutes')
            """,
            (chat_id, thread_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_active_dialogue(chat_id: int, thread_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO dialogue_state (chat_id, thread_id, user_id, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id, thread_id) DO UPDATE SET user_id = excluded.user_id, updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, thread_id, user_id),
        )
        await db.commit()


async def clear_active_dialogue(chat_id: int, thread_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM dialogue_state WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        )
        await db.commit()


# ---------- инициатива через час тишины (функции оставлены, но фоновый цикл их больше не вызывает) ----------

async def _has_later_reply(chat_id: int, thread_id: int, msg_id: int, user_id: int | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE chat_id = ? AND thread_id = ? AND id > ? AND role = 'user'
            AND (telegram_user_id IS NULL OR telegram_user_id != ?)
            """,
            (chat_id, thread_id, msg_id, user_id),
        )
        row = await cursor.fetchone()
        return row[0] > 0


async def mark_followup_done(message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE messages SET followup_done = 1 WHERE id = ?", (message_id,))
        await db.commit()


async def get_pending_followups(chat_id: int, older_than_minutes: int):
    """Весомые сообщения старше N минут, на которые никто не ответил. Уже отвеченные помечает done по пути."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"""
            SELECT id, thread_id, author, content, telegram_user_id FROM messages
            WHERE chat_id = ? AND role = 'user' AND needs_followup = 1 AND followup_done = 0
            AND created_at <= datetime('now', '-{int(older_than_minutes)} minutes')
            ORDER BY id ASC
            """,
            (chat_id,),
        )
        rows = await cursor.fetchall()

    result = []
    for msg_id, thread_id, author, content, user_id in rows:
        if await _has_later_reply(chat_id, thread_id, msg_id, user_id):
            await mark_followup_done(msg_id)
        else:
            result.append((msg_id, thread_id, author, content, user_id))
    return result


# ---------- утренние/вечерние сводки ----------

async def get_digest_last_id(chat_id: int, thread_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_message_id FROM digest_progress WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def set_digest_last_id(chat_id: int, thread_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO digest_progress (chat_id, thread_id, last_message_id) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, thread_id) DO UPDATE SET last_message_id = excluded.last_message_id
            """,
            (chat_id, thread_id, message_id),
        )
        await db.commit()


async def was_digest_sent(chat_id: int, kind: str, date_str: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM digest_log WHERE chat_id = ? AND kind = ? AND sent_date = ?",
            (chat_id, kind, date_str),
        )
        return (await cursor.fetchone()) is not None


async def log_digest_sent(chat_id: int, kind: str, date_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO digest_log (chat_id, kind, sent_date) VALUES (?, ?, ?)",
            (chat_id, kind, date_str),
        )
        await db.commit()


# ---------- глобальная сквозная сводка по всему чату (фон для ответов) ----------

async def get_global_context(chat_id: int) -> tuple[str, str | None]:
    """Возвращает (текст сводки, когда обновлялась). Текст пустой, если сводки ещё не было."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT summary, updated_at FROM global_context WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1]) if row else ("", None)


async def set_global_context(chat_id: int, summary: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO global_context (chat_id, summary, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET summary = excluded.summary, updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, summary),
        )
        await db.commit()


async def get_context_last_id(chat_id: int, thread_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_message_id FROM context_progress WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def set_context_last_id(chat_id: int, thread_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO context_progress (chat_id, thread_id, last_message_id) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, thread_id) DO UPDATE SET last_message_id = excluded.last_message_id
            """,
            (chat_id, thread_id, message_id),
        )
        await db.commit()


# ---------- многочатовость: какие чаты знает бот, темы и настройки по каждому ----------

async def touch_chat(chat_id: int):
    """Отмечает, что бот видел сообщение из этого чата - для фонового цикла по всем чатам."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO known_chats (chat_id) VALUES (?)", (chat_id,))
        await db.commit()


async def get_known_chats() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT chat_id FROM known_chats")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_topic_info_db(chat_id: int, thread_id: int) -> tuple[str, str] | None:
    """Название и фокус темы, если она была настроена командой /setup. None, если ещё не настраивали."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name, focus FROM topic_info WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        )
        row = await cursor.fetchone()
        return (row[0], row[1] or "") if row else None


async def set_topic_info_db(chat_id: int, thread_id: int, name: str, focus: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO topic_info (chat_id, thread_id, name, focus) VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, thread_id) DO UPDATE SET name = excluded.name, focus = excluded.focus
            """,
            (chat_id, thread_id, name, focus),
        )
        await db.commit()


async def get_all_topics(chat_id: int) -> list[tuple[int, str, str]]:
    """Все настроенные темы чата: (thread_id, name, focus)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT thread_id, name, focus FROM topic_info WHERE chat_id = ?",
            (chat_id,),
        )
        return await cursor.fetchall()


async def set_digest_thread(chat_id: int, thread_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO chat_settings (chat_id, digest_thread_id) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET digest_thread_id = excluded.digest_thread_id
            """,
            (chat_id, thread_id),
        )
        await db.commit()


async def get_digest_thread(chat_id: int) -> int | None:
    """Тема, куда присылать утренние/вечерние сводки для этого чата. None, если не настроено."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT digest_thread_id FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None
