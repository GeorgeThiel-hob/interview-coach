"""Accounts by invite code (personal, single use) or the capped shared /demo code: argon2
password hashes, signed session cookies, CSRF tokens."""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Invite, User

_hasher = PasswordHasher()
_attempts: dict[str, list[float]] = {}
LOGIN_LIMIT = 5
LOGIN_WINDOW_S = 600


def login_allowed(key: str) -> bool:
    """At most LOGIN_LIMIT failed attempts per key (ip+username) per window, in memory."""
    import time

    now = time.time()
    recent = [t for t in _attempts.get(key, []) if now - t < LOGIN_WINDOW_S]
    _attempts[key] = recent
    return len(recent) < LOGIN_LIMIT


def record_failed_login(key: str) -> None:
    import time

    _attempts.setdefault(key, []).append(time.time())


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


SHARED_SIGNUP = "shared-signup"  # User.invited_by of accounts made with the shared code


@dataclass(frozen=True)
class SharedSignup:
    """One public code (the /demo "try it yourself" button) that up to max_users people can use.

    Lives in settings, not in the invites table: a new column there would need a migration.
    """

    code: str
    max_users: int
    until: date | None = None

    def matches(self, code: str) -> bool:
        # bytes, not str: compare_digest raises TypeError on non-ASCII str (a pasted
        # zero-width space would otherwise turn every /register attempt into a 500)
        want = self.code.strip().encode()
        return bool(want) and hmac.compare_digest(code.strip().encode(), want)

    def is_open(self, engine: Engine) -> bool:
        """The code is set, not past its end date, and has places left."""
        if not self.code.strip() or (self.until and datetime.now(UTC).date() > self.until):
            return False
        with Session(engine) as s:
            return _shared_count(s) < self.max_users


def _shared_count(s: Session) -> int:
    return len(s.exec(select(User.id).where(User.invited_by == SHARED_SIGNUP)).all())


_USERNAME = re.compile(r"[\w .@-]{3,40}")


def normalize_username(name: str) -> str:
    """The login name: any name or word, 3-40 characters, case-insensitive. No e-mail needed;
    an old e-mail login still fits. Stored in users.email (the column predates the rename)."""
    name = " ".join(name.split()).lower()
    if not _USERNAME.fullmatch(name):
        raise ValueError(
            "Choose a username of 3 to 40 characters: letters, digits, spaces, . _ - or @."
        )
    return name


def register(
    engine: Engine, code: str, username: str, password: str, shared: SharedSignup | None = None
) -> User:
    username = normalize_username(username)
    if len(password) < 10:
        raise ValueError("Use a password of at least 10 characters.")
    if shared and shared.matches(code):
        if not shared.is_open(engine):
            raise ValueError("This code is no longer valid. Ask for a personal invite.")
        return _create_candidate(engine, username, password, invited_by=SHARED_SIGNUP)
    with Session(engine) as s:
        invite = s.get(Invite, code.strip())
        expires = (
            invite.expires_at.replace(tzinfo=UTC)
            if invite and invite.expires_at.tzinfo is None
            else (invite.expires_at if invite else None)
        )
        if invite is None or invite.used_by or (expires and expires < datetime.now(UTC)):
            raise ValueError("This invite code is not valid.")
        if s.exec(select(User).where(User.email == username)).first():
            raise ValueError(USERNAME_TAKEN)
        user = User(
            email=username,
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


USERNAME_TAKEN = "This username is taken. Choose another one."


def _create_candidate(engine: Engine, username: str, password: str, invited_by: str) -> User:
    with Session(engine) as s:
        if s.exec(select(User).where(User.email == username)).first():
            raise ValueError(USERNAME_TAKEN)
        user = User(
            email=username,
            password_hash=hash_password(password),
            role="candidate",
            invited_by=invited_by,
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        return user


def create_user(engine: Engine, username: str, password: str, role: str = "admin") -> User:
    with Session(engine) as s:
        user = User(
            email=" ".join(username.split()).lower(),
            password_hash=hash_password(password),
            role=role,
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        return user


def authenticate(engine: Engine, username: str, password: str) -> User | None:
    name = " ".join(username.split()).lower()
    with Session(engine) as s:
        user = s.exec(select(User).where(User.email == name)).first()
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
