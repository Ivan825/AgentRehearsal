"""Accounts and sessions: email + password, PBKDF2 hashes, HS256 JWTs.

AGENTREHEARSAL_AUTH=off makes every request the anonymous "local" user (CLI, tests, offline demos).
A Cognito user pool can replace this later by verifying its RS256 tokens in `current_user`.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request

from . import config
from .store import get_store

AUTH_ENABLED = os.getenv("AGENTREHEARSAL_AUTH", "on").lower() not in ("off", "0", "false")
TOKEN_TTL_S = 7 * 24 * 3600


def _secret() -> str:
    s = os.getenv("AGENTREHEARSAL_JWT_SECRET")
    if s:
        return s
    p = Path(__file__).resolve().parent.parent / "data" / ".jwt_secret"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(secrets.token_urlsafe(48))
    return p.read_text().strip()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, dk_b64 = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), 200_000)
        return secrets.compare_digest(base64.b64encode(dk).decode(), dk_b64)
    except Exception:
        return False


def issue_token(user: dict[str, Any]) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user["id"], "email": user["email"], "name": user.get("name", ""), "iat": now, "exp": now + TOKEN_TTL_S}, _secret(), algorithm="HS256")


def signup(email: str, password: str, name: str) -> dict[str, Any]:
    email = email.strip().lower()
    if "@" not in email or len(password) < 8:
        raise HTTPException(400, "Enter a valid email and a password of at least 8 characters.")
    store = get_store()
    if store.get_user_by_email(email):
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    user = {"id": uuid.uuid4().hex, "email": email, "name": name.strip() or email.split("@")[0], "password": hash_password(password), "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    store.put_user(user)
    return user


def login(email: str, password: str) -> dict[str, Any]:
    user = get_store().get_user_by_email(email.strip().lower())
    if not user:
        raise HTTPException(401, "No account with that email. Create one first.")
    if not verify_password(password, user["password"]):
        raise HTTPException(401, "Wrong password.")
    return user


ANON = {"id": "local", "email": "local@agentrehearsal", "name": "Local user"}


def current_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency: the signed-in user, or the anonymous local user when auth is off."""
    if not AUTH_ENABLED:
        return ANON
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    try:
        claims = jwt.decode(header[7:], _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid session. Sign in again.")
    return {"id": claims["sub"], "email": claims["email"], "name": claims.get("name", "")}


User = Depends(current_user)
