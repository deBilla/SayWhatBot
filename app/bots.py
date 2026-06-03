"""Runs one long-polling Telegram bot per registered token, all inside the
FastAPI event loop. Voice/audio messages are downloaded and pushed onto the
shared transcription queue (see transcribe.py)."""
import io
import logging

from telegram import Update
from telegram.error import InvalidToken
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import transcribe

log = logging.getLogger("bots")

# Bytes of audio we are willing to download per message (Telegram bot API caps
# downloads at 20MB anyway).
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class BotManager:
    """Starts/stops python-telegram-bot Applications keyed by token."""

    def __init__(self) -> None:
        self._apps: dict[str, Application] = {}

    # --- lifecycle -----------------------------------------------------------

    async def start_all(self) -> None:
        import db
        for row in await db.all_enabled_bots():
            try:
                await self._start(row["token"])
            except Exception:  # noqa: BLE001
                log.exception("Failed to start bot for user_id=%s", row["user_id"])

    async def shutdown(self) -> None:
        for token in list(self._apps):
            await self._stop(token)

    def is_running(self, token: str) -> bool:
        return token in self._apps

    async def validate_token(self, token: str) -> str:
        """Return the bot username if the token is valid, else raise."""
        app = Application.builder().token(token).build()
        await app.initialize()
        try:
            me = await app.bot.get_me()
            return me.username or str(me.id)
        finally:
            await app.shutdown()

    async def connect(self, token: str) -> None:
        await self._stop(token)  # restart cleanly if already running
        await self._start(token)

    async def disconnect(self, token: str) -> None:
        await self._stop(token)

    # --- internals -----------------------------------------------------------

    async def _start(self, token: str) -> None:
        if token in self._apps:
            return
        app = Application.builder().token(token).build()
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._on_voice))
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        self._apps[token] = app
        log.info("Started polling for a bot token ending …%s", token[-6:])

    async def _stop(self, token: str) -> None:
        app = self._apps.pop(token, None)
        if app is None:
            return
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("Error stopping bot")
        log.info("Stopped polling for a bot token ending …%s", token[-6:])

    async def _on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return

        media = message.voice or message.audio
        if media is None:
            return

        if media.file_size and media.file_size > MAX_AUDIO_BYTES:
            await message.reply_text("⚠️ That audio is too large (max 20MB).")
            return

        ahead = transcribe.pending_count()
        position_note = f" You're #{ahead + 1} in the queue." if ahead else ""
        placeholder = await message.reply_text(f"🎙️ Queued…{position_note}")

        try:
            tg_file = await context.bot.get_file(media.file_id)
            buf = io.BytesIO()
            await tg_file.download_to_memory(buf)
        except Exception:  # noqa: BLE001
            log.exception("Failed to download audio")
            await placeholder.edit_text("⚠️ Couldn't download that audio. Please try again.")
            return

        filename = "audio.oga" if message.voice else (media.file_name or "audio")
        await transcribe.enqueue(
            transcribe.Job(
                token=context.bot.token,
                message=placeholder,
                audio=buf.getvalue(),
                filename=filename,
            )
        )


# Re-export for callers that catch invalid tokens.
__all__ = ["BotManager", "InvalidToken"]
