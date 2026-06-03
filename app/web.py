"""Dashboard UI: connect / disconnect a Telegram bot and view its status."""
import logging
import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from telegram.error import InvalidToken

import db
from auth import current_user_id

log = logging.getLogger("web")
router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_bot_manager(request: Request):
    return request.app.state.bot_manager


@router.get("/")
async def index(request: Request):
    if current_user_id(request) is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
async def dashboard(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)

    user = await db.get_user(user_id)
    if user is None:  # stale session
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    bot = await db.get_bot_for_user(user_id)
    manager = get_bot_manager(request)
    running = bool(bot) and manager.is_running(bot["token"])

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "email": user["email"],
            "bot": bot,
            "running": running,
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
        },
    )


def _gen_code() -> str:
    return secrets.token_hex(3)  # 6 hex chars, e.g. "a3f9c1"


@router.post("/bot/connect")
async def connect_bot(request: Request, token: str = Form(...), access_code: str = Form("")):
    user_id = current_user_id(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)

    token = token.strip()
    access_code = access_code.strip() or _gen_code()
    manager = get_bot_manager(request)

    try:
        username = await manager.validate_token(token)
    except InvalidToken:
        return RedirectResponse("/dashboard?error=That+token+is+invalid.", status_code=303)
    except Exception as exc:  # noqa: BLE001
        log.exception("Token validation failed")
        return RedirectResponse(
            f"/dashboard?error=Could+not+verify+token:+{exc}", status_code=303
        )

    await db.upsert_bot(user_id, token, username, access_code)
    try:
        await manager.connect(token)
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to start bot")
        await db.set_bot_error(token, str(exc))
        return RedirectResponse(
            "/dashboard?error=Saved,+but+failed+to+start+polling.", status_code=303
        )

    return RedirectResponse(f"/dashboard?ok=Connected+@{username}", status_code=303)


@router.post("/bot/code")
async def update_code(request: Request, access_code: str = Form("")):
    user_id = current_user_id(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)

    bot = await db.get_bot_for_user(user_id)
    if not bot:
        return RedirectResponse("/dashboard?error=Connect+a+bot+first.", status_code=303)

    await db.set_access_code(user_id, access_code.strip() or _gen_code())
    return RedirectResponse("/dashboard?ok=Access+code+updated.", status_code=303)


@router.post("/bot/disconnect")
async def disconnect_bot(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)

    bot = await db.get_bot_for_user(user_id)
    if bot:
        manager = get_bot_manager(request)
        await manager.disconnect(bot["token"])
        await db.delete_bot_for_user(user_id)

    return RedirectResponse("/dashboard?ok=Bot+disconnected.", status_code=303)
