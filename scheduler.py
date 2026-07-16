import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot

from config import (
    SILENCE_INITIATIVE_MINUTES,
    DIGEST_MORNING_HOUR,
    DIGEST_MORNING_MINUTE,
    DIGEST_EVENING_HOUR,
    DIGEST_EVENING_MINUTE,
    GLOBAL_CONTEXT_UPDATE_MINUTES,
)
from db import (
    get_pending_followups,
    mark_followup_done,
    was_digest_sent,
    log_digest_sent,
    get_digest_last_id,
    set_digest_last_id,
    get_messages_since,
    get_global_context,
    set_global_context,
    get_context_last_id,
    set_context_last_id,
)
from topics import TOPICS, DIGEST_THREAD_ID
from yandex_client import (
    generate_followup_nudge,
    generate_morning_message,
    generate_evening_paragraph,
    generate_global_context_update,
)

MSK = timezone(timedelta(hours=3))
CHECK_INTERVAL_SECONDS = 300  # 5 минут


async def background_loop(bot: Bot, chat_id: int):
    """Единый фоновый цикл: раз в 5 минут проверяет напоминания, сводки и глобальный контекст."""
    while True:
        try:
            await check_followups(bot, chat_id)
        except Exception:
            logging.exception("Ошибка при проверке напоминаний")

        try:
            await check_digests(bot, chat_id)
        except Exception:
            logging.exception("Ошибка при проверке сводок")

        try:
            await check_global_context(chat_id)
        except Exception:
            logging.exception("Ошибка при обновлении сквозной сводки")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def check_followups(bot: Bot, chat_id: int):
    candidates = await get_pending_followups(chat_id, older_than_minutes=SILENCE_INITIATIVE_MINUTES)
    for msg_id, thread_id, author, content, user_id in candidates:
        try:
            nudge = await generate_followup_nudge(author or "кто-то", content)
            mention = f'<a href="tg://user?id={user_id}">{author}</a>' if user_id and author else author
            if mention and mention not in nudge and author and author in nudge:
                nudge = nudge.replace(author, mention, 1)
            await bot.send_message(chat_id, nudge, message_thread_id=thread_id or None)
        except Exception:
            logging.exception(f"Не удалось отправить напоминание для сообщения {msg_id}")
        finally:
            await mark_followup_done(msg_id)


async def check_digests(bot: Bot, chat_id: int):
    now = datetime.now(MSK)
    today = now.strftime("%Y-%m-%d")

    morning_target = now.replace(hour=DIGEST_MORNING_HOUR, minute=DIGEST_MORNING_MINUTE, second=0, microsecond=0)
    if (
        morning_target <= now < morning_target + timedelta(hours=1)
        and not await was_digest_sent(chat_id, "morning", today)
    ):
        text = await generate_morning_message()
        await bot.send_message(chat_id, text, message_thread_id=DIGEST_THREAD_ID)
        await log_digest_sent(chat_id, "morning", today)

    evening_target = now.replace(hour=DIGEST_EVENING_HOUR, minute=DIGEST_EVENING_MINUTE, second=0, microsecond=0)
    if (
        evening_target <= now < evening_target + timedelta(hours=1)
        and not await was_digest_sent(chat_id, "evening", today)
    ):
        parts = []
        for thread_id, info in TOPICS.items():
            if thread_id in (0, DIGEST_THREAD_ID):
                continue
            since_id = await get_digest_last_id(chat_id, thread_id)
            history = await get_messages_since(chat_id, thread_id, since_id)
            if not history:
                continue
            paragraph = await generate_evening_paragraph(history, info["name"])
            parts.append(f"<b>{info['name']}</b>\n{paragraph}")
            latest_id = history[-1][0]
            await set_digest_last_id(chat_id, thread_id, latest_id)

        digest_text = "\n\n".join(parts) if parts else "Сегодня в ветках было тихо."
        await bot.send_message(chat_id, digest_text, message_thread_id=DIGEST_THREAD_ID)
        await log_digest_sent(chat_id, "evening", today)


async def check_global_context(chat_id: int):
    """Раз в GLOBAL_CONTEXT_UPDATE_MINUTES обновляет компактную сквозную сводку по всем темам."""
    previous_summary, updated_at = await get_global_context(chat_id)

    if updated_at:
        last_update = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_update < timedelta(minutes=GLOBAL_CONTEXT_UPDATE_MINUTES):
            return  # ещё не пора

    material_parts = []
    updates_to_commit = []  # (thread_id, latest_id) - применяем только если реально были новые сообщения

    for thread_id, info in TOPICS.items():
        if thread_id in (0, DIGEST_THREAD_ID):
            continue
        since_id = await get_context_last_id(chat_id, thread_id)
        history = await get_messages_since(chat_id, thread_id, since_id, max_messages=100)
        if not history:
            continue

        lines = []
        for _id, role, author, content in history:
            if role == "assistant":
                lines.append(f"Люмен: {content}")
            else:
                lines.append(f"{author or 'кто-то'}: {content}")
        material_parts.append(f"[{info['name']}]\n" + "\n".join(lines))
        updates_to_commit.append((thread_id, history[-1][0]))

    if not material_parts:
        return  # ничего нового ни в одной теме - сводку обновлять не о чем

    new_material = "\n\n".join(material_parts)
    new_summary = await generate_global_context_update(previous_summary, new_material)
    await set_global_context(chat_id, new_summary)

    for thread_id, latest_id in updates_to_commit:
        await set_context_last_id(chat_id, thread_id, latest_id)
