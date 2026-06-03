"""Signup / login / logout and session helpers."""
import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext

import db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _pwd.verify(password, hashed)
    except Exception:
        return False


def current_user_id(request: Request) -> int | None:
    return request.session.get("user_id")


@router.get("/signup")
async def signup_form(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})


@router.post("/signup")
async def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return _err("signup.html", request, "Please enter a valid email address.")
    if len(password) < 8:
        return _err("signup.html", request, "Password must be at least 8 characters.")
    if await db.get_user_by_email(email):
        return _err("signup.html", request, "That email is already registered.")

    user_id = await db.create_user(email, hash_password(password))
    request.session["user_id"] = user_id
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    user = await db.get_user_by_email(email)
    if user is None or not verify_password(password, user["password_hash"]):
        return _err("login.html", request, "Invalid email or password.")
    request.session["user_id"] = user["id"]
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _err(template: str, request: Request, message: str):
    return templates.TemplateResponse(
        template, {"request": request, "error": message}, status_code=400
    )
