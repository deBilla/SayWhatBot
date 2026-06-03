# SayWhatBot 🎙️

Self-hosted server that transcribes **Telegram voice notes** using a locally
running **Whisper** model. Runs entirely with Docker Compose — no cloud APIs.

- **Bring your own bot.** A simple web UI lets you create an account and connect
  your own Telegram bot (created via [@BotFather](https://t.me/BotFather)).
- **Multi-user.** Many people can use their bots at once; requests are queued.
- **One transcription at a time.** A single global worker funnels every request
  through Whisper sequentially, so the local model is never overloaded.

## Architecture

```
Telegram ──voice note──▶  app (FastAPI)            ┌──────────────┐
                          ├─ web UI (accounts)     │   whisper    │
                          ├─ 1 poller per bot ─────▶  /asr (HTTP) │
                          └─ single queue + worker  └──────────────┘
```

Two containers:

| Service   | What it does                                                        |
|-----------|---------------------------------------------------------------------|
| `whisper` | `onerahmet/openai-whisper-asr-webservice` — ASR over HTTP on `:9000` |
| `app`     | FastAPI: web UI, accounts (SQLite), per-bot pollers, transcribe queue |

## Quick start

```bash
cp .env.example .env
# Generate a session secret and put it in .env:
python -c "import secrets; print('APP_SECRET=' + secrets.token_hex(32))"

docker compose up --build
```

First boot downloads the Whisper model (~140MB for `base`) into a named volume,
so it's cached for subsequent runs. The `app` waits until Whisper is healthy.

Then open **http://localhost:8000** and:

1. **Sign up** with an email + password.
2. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
   and copy the token it gives you.
3. Paste the token into the dashboard and click **Connect bot**.
4. Open your bot in Telegram and send it a **voice note** — you'll get the
   transcription back (it edits a "Queued…/Transcribing…" message in place).

## Configuration (`.env`)

| Variable          | Default          | Notes                                              |
|-------------------|------------------|----------------------------------------------------|
| `APP_SECRET`      | _(required)_     | Random string used to sign login sessions          |
| `ASR_MODEL`       | `base`           | `tiny`/`base`/`small`/`medium`/`large-v3` — accuracy vs speed |
| `ASR_ENGINE`      | `faster_whisper` | `faster_whisper` (lighter) or `openai_whisper`      |
| `WHISPER_TASK`    | `transcribe`     | `translate` to translate speech into English        |
| `WHISPER_LANGUAGE`| _(empty)_        | Force a language code (e.g. `en`); empty = auto      |
| `PORT`            | `8000`           | Host port for the web UI                            |

Want better accuracy? Set `ASR_MODEL=small` (or `medium`) in `.env` and
`docker compose up -d`. Bigger models are slower and need more RAM/CPU; for
`large` models a GPU is strongly recommended.

## Notes & limits

- Telegram's bot API caps file downloads at **20MB** per audio message.
- Data (accounts + connected bots) is stored in `app/data/app.db`, bind-mounted
  so it survives rebuilds.
- This is designed for CPU. To use a GPU, switch to a CUDA Whisper image and add
  the appropriate `deploy.resources` reservations to `docker-compose.yml`.

## Development

```bash
docker compose logs -f app       # watch the bot pollers + transcription worker
docker compose restart app       # reload after code changes
docker compose down              # stop everything (keeps the model cache volume)
```
