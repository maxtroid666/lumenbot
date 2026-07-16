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
)
from topics import get_topic_info
from yandex_client import generate_reply, generate_summary

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


async def _do_summary(message: Message):
    chat_id = message.chat.id
    thread_id = message.message_thread_id or 0
    topic = get_topic_info(thread_id)

    since_id = await get_last_summary_id(chat_id, thread_id)
    history = await get_messages_since(chat_id, thread_id, since_id)
    summary_text = await generate_summary(history, topic_name=topic["name"])

    latest_id = await get_latest_message_id(chat_id, thread_id)
    if latest_id:
        await set_last_summary_id(chat_id, thread_id, latest_id)

    await save_message(chat_id, "assistant", summary_text, thread_id=thread_id)
    await message.reply(summary_text)


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

    topic = get_topic_info(thread_id)
    history = await get_history(chat_id, thread_id, HISTORY_LIMIT)
    reply_text = await generate_reply(history, topic_name=topic["name"], topic_focus=topic["focus"])

    await save_message(chat_id, "assistant", reply_text, thread_id=thread_id)
    await message.reply(reply_text)

    # диалог считается открытым до тайм-аута или до "добро"
    if user_id:
        await set_active_dialogue(chat_id, thread_id, user_id)
