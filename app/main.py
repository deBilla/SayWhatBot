"""SayWhatBot — FastAPI app wiring together auth, dashboard, the per-token bot
pollers, and the single global transcription worker."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import auth
import config
import db
import transcribe
import web
from bots import BotManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    transcribe.start_worker()

    manager = BotManager()
    app.state.bot_manager = manager
    await manager.start_all()
    log.info("SayWhatBot started")

    try:
        yield
    finally:
        await manager.shutdown()
        await transcribe.stop_worker()
        log.info("SayWhatBot stopped")


app = FastAPI(title="SayWhatBot", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.APP_SECRET, max_age=60 * 60 * 24 * 14)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(web.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
