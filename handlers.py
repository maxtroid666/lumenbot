import random
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from config import TRIGGER_WORDS, RANDOM_REPLY_CHANCE, HISTORY_LIMIT, DIALOGUE_TIMEOUT_MINUTES
from db import (
    save_message,
    get_history,
    get_last_summary_id,
    set_last_summary_id,
    get_messages_since,
    get_latest_message_id,
    get_active_dialogue,
    set_active_dialogue,
    clear_active_dialogue,
    get_global_context,
    touch_chat,
    get_topic_info_db,
    set_topic_info_db,
    get_all_topics,
    set_digest_thread,
)
from claude_client import generate_reply, generate_summary

router = Router()

SUMMARY_KEYWORDS = ("итоги", "саммари", "summary")
FOLLOWUP_KEYWORDS = ("надо ", "нужно ", "необходимо ", "не забыть", "напомни", "дедлайн", "срочно")


def is_closing(text: str) -> bool:
    """"Добро" (и вариации типа "добро!", "добро, спасибо") - сигнал, что разговор закрыт."""
    t = text.lower().strip().strip("!.,")
    return t == "добро" or t.startswith("добро ") or t.startswith("добро,")


def is_weighty(text: str, is_reply_to_someone: bool) -> bool:
    """Эвристика "весомого" сообщения - кандидат на напоминание через час тишины."""
    t = text.strip()
    if not t or is_reply_to_someone:
        return False
    if t.endswith("?"):
        return True
    low = t.lower()
    return any(kw in low for kw in FOLLOWUP_KEYWORDS)


def should_reply_by_trigger(message: Message, bot_username: str) -> bool:
    text = (message.text or message.caption or "").lower()

    # ответили реплаем на сообщение бота
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.username == bot_username
    ):
        return True

    # бота упомянули через @username
    if bot_username and f"@{bot_username.lower()}" in text:
        return True

    # сработало триггер-слово
    if any(word in text for word in TRIGGER_WORDS):
        return True

    # случайное включение в разговор
    if random.random() < RANDOM_REPLY_CHANCE:
        return True

    return False


async def _resolve_topic(chat_id: int, thread_id: int) -> tuple[str, str]:
    """Название и фокус текущей темы. Если тема не настроена командой /setup - дефолт по номеру."""
    row = await get_topic_info_db(chat_id, thread_id)
    if row:
        return row
    if thread_id == 0:
        return "Общее", ""
    return f"тема {thread_id}", ""


def _find_referenced_topic(
    text: str,
    topics: list[tuple[int, str, str]],
    current_thread_id: int,
    digest_thread_id: int | None,
) -> tuple[int | None, str | None]:
    """Ищет в тексте упоминание названия ДРУГОЙ настроенной темы этого же чата - для прицельного обращения."""
    low = text.lower()
    for thread_id, name, focus in topics:
        if thread_id == current_thread_id or thread_id == digest_thread_id:
            continue
        if name and name.lower() in low:
            return thread_id, name
    return None, None


async def _do_summary(message: Message):
    chat_id = message.chat.id
    thread_id = message.message_thread_id or 0
    topic_name, _ = await _resolve_topic(chat_id, thread_id)

    since_id = await get_last_summary_id(chat_id, thread_id)
    history = await get_messages_since(chat_id, thread_id, since_id)
    summary_text = await generate_summary(history, topic_name=topic_name)

    latest_id = await get_latest_message_id(chat_id, thread_id)
    if latest_id:
        await set_last_summary_id(chat_id, thread_id, latest_id)

    await save_message(chat_id, "assistant", summary_text, thread_id=thread_id)
    await message.reply(summary_text)


@router.message(Command("setup"))
async def cmd_setup(message: Message):
    """Настройка названия/фокуса текущей темы: /setup Название - фокус (необязательно)."""
    text = message.text or ""
    rest = text.partition(" ")[2].strip()
    if not rest:
        await message.reply(
            "Формат: /setup Название темы - фокус (необязательно)\n"
            "Пример: /setup Дизайн - обсуждение визуального стиля"
        )
        return

    if " - " in rest:
        name, focus = rest.split(" - ", 1)
    else:
        name, focus = rest, ""

    thread_id = message.message_thread_id or 0
    await set_topic_info_db(message.chat.id, thread_id, name.strip(), focus.strip())

    reply = f"Записал: эта тема - «{name.strip()}»"
    if focus.strip():
        reply += f" ({focus.strip()})"
    reply += "."
    await message.reply(reply)


@router.message(Command("setup_digest"))
async def cmd_setup_digest(message: Message):
    """Назначает текущую тему местом для утренних/вечерних сводок этого чата."""
    thread_id = message.message_thread_id or 0
    await set_digest_thread(message.chat.id, thread_id)
    await message.reply("Записал: сюда буду присылать утренние и вечерние сводки.")


@router.message(Command("summary"))
async def cmd_summary(message: Message):
    await _do_summary(message)


@router.message(F.text | F.caption)
async def on_message(message: Message, bot_username: str):
    text = message.text or message.caption or ""
    author = message.from_user.full_name if message.from_user else "аноним"
    user_id = message.from_user.id if message.from_user else None
    thread_id = message.message_thread_id or 0
    chat_id = message.chat.id

    # отмечаем чат как известный - фоновый цикл сам найдёт все такие чаты
    await touch_chat(chat_id)

    # реплай на бота не считается "реплаем на кого-то" в смысле весомости
    is_reply_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.username == bot_username
    )
    is_reply_to_someone = bool(message.reply_to_message) and not is_reply_to_bot
    weighty = is_weighty(text, is_reply_to_someone)

    # запоминаем реплику в любом случае - это и есть память чата
    await save_message(
        chat_id, "user", text, author,
        thread_id=thread_id, telegram_user_id=user_id, needs_followup=weighty,
    )

    # закрывающая фраза "добро" - гасим открытый диалог и не отвечаем
    if is_closing(text):
        await clear_active_dialogue(chat_id, thread_id)
        return

    triggered = should_reply_by_trigger(message, bot_username)

    active_user_id = await get_active_dialogue(chat_id, thread_id, DIALOGUE_TIMEOUT_MINUTES)
    continuing_dialogue = (not triggered) and active_user_id is not None and user_id == active_user_id

    if not triggered and not continuing_dialogue:
        return

    if any(word in text.lower() for word in SUMMARY_KEYWORDS):
        await _do_summary(message)
        if user_id:
            await set_active_dialogue(chat_id, thread_id, user_id)
        return

    topic_name, topic_focus = await _resolve_topic(chat_id, thread_id)
    history = await get_history(chat_id, thread_id, HISTORY_LIMIT)
    global_context, _ = await get_global_context(chat_id)

    # прицельное обращение к другой теме этого же чата по названию ("а что там было про дизайн")
    all_topics = await get_all_topics(chat_id)
    ref_thread_id, ref_name = _find_referenced_topic(text, all_topics, thread_id, None)
    referenced_topic = None
    if ref_thread_id is not None:
        ref_history = await get_history(chat_id, ref_thread_id, 15)
        referenced_topic = (ref_name, ref_history)

    reply_text = await generate_reply(
        history,
        topic_name=topic_name,
        topic_focus=topic_focus,
        global_context=global_context,
        referenced_topic=referenced_topic,
    )

    await save_message(chat_id, "assistant", reply_text, thread_id=thread_id)
    await message.reply(reply_text)

    # диалог считается открытым до тайм-аута или до "добро"
    if user_id:
        await set_active_dialogue(chat_id, thread_id, user_id)
