import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, YANDEX_API_KEY, YANDEX_FOLDER_ID
from db import init_db
from handlers import router
from scheduler import background_loop

logging.basicConfig(level=logging.INFO)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN (переменная окружения)")
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        raise RuntimeError("Не заданы YANDEX_API_KEY / YANDEX_FOLDER_ID (переменные окружения)")

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    logging.info(f"Бот запущен: @{me.username}")

    # фоновый цикл: напоминания, сводки и глобальный контекст - по всем чатам, куда добавлен бот
    asyncio.create_task(background_loop(bot))

    # прокидываем username бота во все хендлеры, чтобы не дёргать get_me() на каждом сообщении
    await dp.start_polling(bot, bot_username=me.username)


if __name__ == "__main__":
    asyncio.run(main())
