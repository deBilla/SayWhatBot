"""Single global transcription queue + one worker.

Every voice note from every bot/user is pushed onto one asyncio.Queue and
processed by exactly ONE worker coroutine. This guarantees that the locally
running Whisper model only ever handles one transcription at a time, no matter
how many users are sending audio concurrently.
"""
import asyncio
import io
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import httpx
from telegram import Message

import config

log = logging.getLogger("transcribe")


@dataclass
class Job:
    token: str           # which bot owns this (for error bookkeeping)
    message: Message     # the placeholder reply we will edit with the result
    audio: bytes         # raw audio bytes downloaded from Telegram
    filename: str        # e.g. "voice.oga"


_queue: "asyncio.Queue[Job]" = asyncio.Queue()


def pending_count() -> int:
    """How many jobs are waiting ahead (not counting the one in progress)."""
    return _queue.qsize()


async def enqueue(job: Job) -> None:
    await _queue.put(job)


async def _transcode_to_wav(audio: bytes, filename: str) -> Optional[bytes]:
    """Decode any input to 16kHz mono WAV using ffmpeg.

    ffmpeg reads from a seekable temp file (not stdin), so container formats like
    m4a/mp4 — which the Whisper webservice cannot decode from its stdin pipe —
    transcode correctly. Returns None if ffmpeg is unavailable or fails.
    """
    suffix = os.path.splitext(filename)[1] or ".bin"
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, f"in{suffix}")
        out = os.path.join(d, "out.wav")
        with open(inp, "wb") as fh:
            fh.write(audio)
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", inp, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", out,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.warning("ffmpeg not found; sending original audio to Whisper")
            return None
        _, err = await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(out):
            log.warning("ffmpeg transcode failed: %s", err.decode("utf-8", "replace")[:300])
            return None
        with open(out, "rb") as fh:
            return fh.read()


async def _call_whisper(audio: bytes, filename: str) -> str:
    params = {"task": config.WHISPER_TASK, "output": "txt"}
    if config.WHISPER_LANGUAGE:
        params["language"] = config.WHISPER_LANGUAGE

    wav = await _transcode_to_wav(audio, filename)
    if wav is not None:
        # Already 16kHz mono PCM WAV — tell Whisper to skip its own ffmpeg step.
        audio, filename, params["encode"] = wav, "audio.wav", "false"
    else:
        params["encode"] = "true"

    files = {"audio_file": (filename, audio, "application/octet-stream")}
    log.info("whisper request: %s bytes, filename=%s, encode=%s", len(audio), filename, params["encode"])
    async with httpx.AsyncClient(timeout=config.WHISPER_TIMEOUT) as client:
        resp = await client.post(f"{config.WHISPER_URL}/asr", params=params, files=files)
        resp.raise_for_status()
        text = resp.text.strip()
        log.info("whisper response: status=%s, %s chars", resp.status_code, len(text))
        return text


async def _process(job: Job) -> None:
    try:
        await job.message.edit_text("📝 Transcribing…")
    except Exception:  # message may have been deleted; ignore
        pass

    try:
        text = await _call_whisper(job.audio, job.filename)
    except Exception as exc:  # noqa: BLE001
        log.exception("Transcription failed")
        import db  # local import to avoid a cycle at module load
        await db.set_bot_error(job.token, str(exc))
        await _safe_edit(job.message, "⚠️ Sorry, transcription failed. Please try again.")
        return

    await _deliver(job.message, text)


# Telegram rejects any single message longer than this.
TELEGRAM_LIMIT = 4096


async def _deliver(message: Message, text: str) -> None:
    """Return the transcript to the user.

    Short transcripts replace the "Transcribing…" placeholder in place. Long
    ones (a 49-min recording is tens of thousands of chars) can't fit in one
    message, so we attach the full text as a .txt file instead of silently
    truncating at 4096 chars.
    """
    if not text:
        await _safe_edit(message, "🤔 No speech detected.")
        return
    if len(text) <= TELEGRAM_LIMIT:
        await _safe_edit(message, text)
        return

    try:
        bio = io.BytesIO(text.encode("utf-8"))
        bio.name = "transcript.txt"
        await message.reply_document(
            document=bio,
            filename="transcript.txt",
            caption=f"📝 Transcript ({len(text):,} chars) — too long for a message, sent as a file.",
        )
        await _safe_edit(message, "📝 Transcript attached below ⬇️")
    except Exception:
        log.warning("Could not send transcript as a document; falling back to truncated message")
        await _safe_edit(message, text[:TELEGRAM_LIMIT])


async def _safe_edit(message: Message, text: str) -> None:
    # Telegram caps message length at 4096 chars.
    chunk = text[:TELEGRAM_LIMIT]
    try:
        await message.edit_text(chunk)
    except Exception:
        logging.getLogger("transcribe").warning("Could not edit reply message")


async def worker() -> None:
    log.info("Transcription worker started")
    while True:
        job = await _queue.get()
        try:
            await _process(job)
        except Exception:  # noqa: BLE001
            log.exception("Unexpected worker error")
        finally:
            _queue.task_done()


_worker_task: Optional[asyncio.Task] = None


def start_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(worker())


async def stop_worker() -> None:
    if _worker_task is not None:
        _worker_task.cancel()
