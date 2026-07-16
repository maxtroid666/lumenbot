import random
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from config import TRIGGER_WORDS, RANDOM_REPLY_CHANCE, HISTORY_LIMIT
from db import (
    save_message,
    get_history,
    get_last_summary_id,
    set_last_summary_id,
    get_messages_since,
    get_latest_message_id,
)
from topics import get_topic_info
from yandex_client import generate_reply, generate_summary

router = Router()

SUMMARY_KEYWORDS = ("итоги", "саммари", "summary")


def should_reply(message: Message, bot_username: str) -> bool:
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
    thread_id = message.message_thread_id or 0

    # запоминаем реплику в любом случае — это и есть память чата
    await save_message(message.chat.id, "user", text, author, thread_id=thread_id)

    if not should_reply(message, bot_username):
        return

    # если позвали и явно просят итоги/саммари - отдаём саммари, а не обычный ответ
    if any(word in text.lower() for word in SUMMARY_KEYWORDS):
        await _do_summary(message)
        return

    topic = get_topic_info(thread_id)
    history = await get_history(message.chat.id, thread_id, HISTORY_LIMIT)
    reply_text = await generate_reply(history, topic_name=topic["name"], topic_focus=topic["focus"])

    await save_message(message.chat.id, "assistant", reply_text, thread_id=thread_id)
    await message.reply(reply_text)
