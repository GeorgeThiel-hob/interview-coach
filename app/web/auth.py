"""Invite-only accounts: argon2 password hashes, signed session cookies, CSRF tokens."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Invite, User

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_invite(engine: Engine, created_by: str, role: str = "candidate", days: int = 14) -> str:
    code = secrets.token_urlsafe(12)
    with Session(engine) as s:
        s.add(
            Invite(
                code=code,
                created_by=created_by,
                role=role,
                expires_at=datetime.now(UTC) + timedelta(days=days),
            )
        )
        s.commit()
    return code


def register(engine: Engine, code: str, email: str, password: str) -> User:
    email = email.strip().lower()
    if len(password) < 10:
        raise ValueError("Use a password of at least 10 characters.")
    with Session(engine) as s:
        invite = s.get(Invite, code.strip())
        expires = (
            invite.expires_at.replace(tzinfo=UTC)
            if invite and invite.expires_at.tzinfo is None
            else (invite.expires_at if invite else None)
        )
        if invite is None or invite.used_by or (expires and expires < datetime.now(UTC)):
            raise ValueError("This invite code is not valid.")
        if s.exec(select(User).where(User.email == email)).first():
            raise ValueError("An account with this email already exists.")
        user = User(
            email=email,
            password_hash=hash_password(password),
            role=invite.role,
            invited_by=invite.created_by,
        )
        s.add(user)
        invite.used_by = user.id
        s.add(invite)
        s.commit()
        s.refresh(user)
        return user


def create_user(engine: Engine, email: str, password: str, role: str = "admin") -> User:
    with Session(engine) as s:
        user = User(email=email.strip().lower(), password_hash=hash_password(password), role=role)
        s.add(user)
        s.commit()
        s.refresh(user)
        return user


def authenticate(engine: Engine, email: str, password: str) -> User | None:
    with Session(engine) as s:
        user = s.exec(select(User).where(User.email == email.strip().lower())).first()
    if user is None:
        verify_password(_DUMMY, password)  # same timing as a real check
        return None
    return user if verify_password(user.password_hash, password) else None


_DUMMY = _hasher.hash("timing-equaliser")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return str(token)


async def check_csrf(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = request.session.get("csrf")
    sent = request.headers.get("x-csrf-token")
    if sent is None:
        form = await request.form()
        value = form.get("csrf")
        sent = value if isinstance(value, str) else None
    if not expected or not sent or not hmac.compare_digest(str(expected), sent):
        raise HTTPException(status_code=403, detail="CSRF check failed; reload the page.")


def current_user(request: Request) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    with Session(request.app.state.engine) as s:
        return s.get(User, uid)
