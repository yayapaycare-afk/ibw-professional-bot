import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from app.config import get_settings
from app.db import init_db
from app.bot import create_dispatcher
from app.admin import build_admin_app

settings = get_settings()
bot_task = None
bot_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_task, bot_instance
    await init_db()
    if settings.bot_token:
        bot_instance = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = create_dispatcher()
        await bot_instance.delete_webhook(drop_pending_updates=False)
        bot_task = asyncio.create_task(dispatcher.start_polling(bot_instance))
    yield
    if bot_task:
        bot_task.cancel()
        with suppress(asyncio.CancelledError): await bot_task
    if bot_instance: await bot_instance.session.close()


web_app = FastAPI(lifespan=lifespan)
web_app.mount("/", build_admin_app())
