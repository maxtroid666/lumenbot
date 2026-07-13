import random
from aiogram import Router, F
from aiogram.types import Message

from config import TRIGGER_WORDS, RANDOM_REPLY_CHANCE, HISTORY_LIMIT
from db import save_message, get_history
from yandex_client import generate_reply

router = Router()


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


@router.message(F.text | F.caption)
async def on_message(message: Message, bot_username: str):
    text = message.text or message.caption or ""
    author = message.from_user.full_name if message.from_user else "аноним"

    # запоминаем реплику в любом случае - это и есть память чата
    await save_message(message.chat.id, "user", text, author)

    if not should_reply(message, bot_username):
        return

    history = await get_history(message.chat.id, HISTORY_LIMIT)
    reply_text = await generate_reply(history)

    await save_message(message.chat.id, "assistant", reply_text)
    await message.reply(reply_text)
