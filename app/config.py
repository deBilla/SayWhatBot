"""Environment-driven configuration."""
import os

# Secret used to sign session cookies.
APP_SECRET = os.environ.get("APP_SECRET", "dev-insecure-secret-change-me")

# Base URL of the Whisper ASR webservice (compose service name on the network).
WHISPER_URL = os.environ.get("WHISPER_URL", "http://whisper:9000").rstrip("/")

# "transcribe" (keep language) or "translate" (to English).
WHISPER_TASK = os.environ.get("WHISPER_TASK", "transcribe") or "transcribe"

# Optional forced language (ISO code). Empty => auto-detect.
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "").strip()

# Where the SQLite database lives.
DB_PATH = os.environ.get("DB_PATH", "/app/data/app.db")

# Max time to wait for a single transcription (seconds).
WHISPER_TIMEOUT = float(os.environ.get("WHISPER_TIMEOUT", "300"))
