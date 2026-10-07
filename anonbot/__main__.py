"""Запуск: python -m anonbot"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from .db import Database
from .handlers import router


async def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан BOT_TOKEN (см. .env.example)")

    db = Database(os.getenv("DB_PATH", "anonbot.db"))
    await db.connect()

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()

    dp = Dispatcher(db=db, bot_username=me.username)
    dp.include_router(router)

    logging.getLogger(__name__).info("Бот @%s запущен", me.username)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
