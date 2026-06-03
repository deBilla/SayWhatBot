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
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_error    TEXT,
    created_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return _dt.datetime.utcnow().isoformat(timespec="seconds")


async def init() -> None:
    async with aiosqlite.connect(config.DB_PATH) as conn:
        await conn.executescript(_SCHEMA)
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


async def upsert_bot(user_id: int, token: str, bot_username: str) -> None:
    async with _connect() as conn:
        await conn.execute(
            """
            INSERT INTO bots (user_id, token, bot_username, enabled, last_error, created_at)
            VALUES (?, ?, ?, 1, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                token = excluded.token,
                bot_username = excluded.bot_username,
                enabled = 1,
                last_error = NULL
            """,
            (user_id, token, bot_username, _now()),
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
