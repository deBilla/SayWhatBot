"""Tiny async SQLite data layer for users and their connected bots."""
import datetime as _dt
from contextlib import asynccontextmanager

import aiosqlite

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    token         TEXT NOT NULL,
    bot_username  TEXT,
    access_code   TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_error    TEXT,
    created_at    TEXT NOT NULL
);

-- Telegram chats that have unlocked a bot with its access code.
CREATE TABLE IF NOT EXISTS authorized_chats (
    bot_id     INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    chat_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (bot_id, chat_id)
);
"""


def _now() -> str:
    return _dt.datetime.utcnow().isoformat(timespec="seconds")


async def init() -> None:
    async with aiosqlite.connect(config.DB_PATH) as conn:
        await conn.executescript(_SCHEMA)
        # Migration for DBs created before access_code existed.
        try:
            await conn.execute("ALTER TABLE bots ADD COLUMN access_code TEXT")
        except Exception:
            pass  # column already exists
        await conn.commit()


@asynccontextmanager
async def _connect():
    conn = await aiosqlite.connect(config.DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        await conn.close()


# --- users -------------------------------------------------------------------

async def create_user(email: str, password_hash: str) -> int:
    async with _connect() as conn:
        cur = await conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, _now()),
        )
        await conn.commit()
        return cur.lastrowid


async def get_user_by_email(email: str) -> aiosqlite.Row | None:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        return await cur.fetchone()


async def get_user(user_id: int) -> aiosqlite.Row | None:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return await cur.fetchone()


# --- bots --------------------------------------------------------------------

async def get_bot_for_user(user_id: int) -> aiosqlite.Row | None:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM bots WHERE user_id = ?", (user_id,))
        return await cur.fetchone()


async def upsert_bot(user_id: int, token: str, bot_username: str, access_code: str) -> None:
    async with _connect() as conn:
        await conn.execute(
            """
            INSERT INTO bots (user_id, token, bot_username, access_code, enabled, last_error, created_at)
            VALUES (?, ?, ?, ?, 1, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                token = excluded.token,
                bot_username = excluded.bot_username,
                access_code = excluded.access_code,
                enabled = 1,
                last_error = NULL
            """,
            (user_id, token, bot_username, access_code, _now()),
        )
        await conn.commit()


async def get_bot_by_token(token: str) -> aiosqlite.Row | None:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM bots WHERE token = ?", (token,))
        return await cur.fetchone()


async def set_access_code(user_id: int, access_code: str) -> None:
    async with _connect() as conn:
        await conn.execute(
            "UPDATE bots SET access_code = ? WHERE user_id = ?", (access_code, user_id)
        )
        await conn.commit()


async def is_chat_authorized(bot_id: int, chat_id: int) -> bool:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM authorized_chats WHERE bot_id = ? AND chat_id = ?",
            (bot_id, chat_id),
        )
        return await cur.fetchone() is not None


async def authorize_chat(bot_id: int, chat_id: int) -> None:
    async with _connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO authorized_chats (bot_id, chat_id, created_at) VALUES (?, ?, ?)",
            (bot_id, chat_id, _now()),
        )
        await conn.commit()


async def delete_bot_for_user(user_id: int) -> None:
    async with _connect() as conn:
        await conn.execute("DELETE FROM bots WHERE user_id = ?", (user_id,))
        await conn.commit()


async def set_bot_error(token: str, error: str | None) -> None:
    async with _connect() as conn:
        await conn.execute("UPDATE bots SET last_error = ? WHERE token = ?", (error, token))
        await conn.commit()


async def all_enabled_bots() -> list[aiosqlite.Row]:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM bots WHERE enabled = 1")
        return list(await cur.fetchall())
