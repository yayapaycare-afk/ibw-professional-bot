import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from aiogram import Bot
from app.config import get_settings
from app.db import init_db
from app.bot import create_dispatcher
from app.admin import build_admin_app

settings=get_settings(); bot_task=None

@asynccontextmanager
async def lifespan(app:FastAPI):
    global bot_task
    await init_db()
    if settings.bot_token:
        bot=Bot(settings.bot_token); dp=create_dispatcher(); bot_task=asyncio.create_task(dp.start_polling(bot))
    yield
    if bot_task: bot_task.cancel()

web_app=FastAPI(lifespan=lifespan)
web_app.mount('/',build_admin_app())
