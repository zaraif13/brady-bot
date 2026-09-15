"""User store and password hashing for Brady Bot login."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brady_bot.paths import DATA_DIR

ADMIN_PASSWORD = "Smully1504cyat!"
SUPERADMIN_USERNAME = "12zhossain@gmail.com"
SUPERADMIN_PASSWORD = "Smully1504cyat!"
SUPERADMIN_ID = "superadmin"
USERS_PATH = DATA_DIR / "users.json"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PBKDF2_ITERATIONS = 200_000


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return secrets.compare_digest(candidate, password_hash)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_email(username: str) -> str:
    email = normalize_username(username)
    if not _EMAIL_RE.match(email):
        raise ValueError("Username must be a valid email address")
    return email


def load_users(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or USERS_PATH
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    if isinstance(raw, dict):
        return list(raw.get("users") or [])
    if isinstance(raw, list):
        return raw
    return []


def save_users(users: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or USERS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"users": users}, indent=2) + "\n")


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "created_at": user.get("created_at"),
    }


def find_user_by_username(
    username: str, path: Path | None = None
) -> dict[str, Any] | None:
    email = normalize_username(username)
    for u in load_users(path):
        if normalize_username(u.get("username", "")) == email:
            return u
    return None


def find_user_by_id(user_id: str, path: Path | None = None) -> dict[str, Any] | None:
    for u in load_users(path):
        if u.get("id") == user_id:
            return u
    return None


def _superadmin_user() -> dict[str, Any]:
    return {
        "id": SUPERADMIN_ID,
        "username": SUPERADMIN_USERNAME,
        "created_at": None,
    }


def authenticate(username: str, password: str, path: Path | None = None) -> dict[str, Any] | None:
    email = normalize_username(username)
    if email == SUPERADMIN_USERNAME and secrets.compare_digest(password, SUPERADMIN_PASSWORD):
        return _superadmin_user()
    user = find_user_by_username(username, path)
    if not user:
        return None
    if not verify_password(password, user["password_hash"], user["salt"]):
        return None
    return user


def create_user(username: str, password: str, path: Path | None = None) -> dict[str, Any]:
    email = validate_email(username)
    if not password:
        raise ValueError("Password is required")
    users = load_users(path)
    if any(normalize_username(u.get("username", "")) == email for u in users):
        raise ValueError("A user with that email already exists")
    pw_hash, salt = hash_password(password)
    user = {
        "id": str(uuid.uuid4()),
        "username": email,
        "password_hash": pw_hash,
        "salt": salt,
        "created_at": _utcnow(),
    }
    users.append(user)
    save_users(users, path)
    return user


def update_user(
    user_id: str,
    *,
    username: str | None = None,
    password: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    users = load_users(path)
    idx = next((i for i, u in enumerate(users) if u.get("id") == user_id), None)
    if idx is None:
        raise KeyError("User not found")
    user = dict(users[idx])
    if username is not None:
        email = validate_email(username)
        if any(
            normalize_username(u.get("username", "")) == email and u.get("id") != user_id
            for u in users
        ):
            raise ValueError("A user with that email already exists")
        user["username"] = email
    if password is not None:
        if not password:
            raise ValueError("Password cannot be empty")
        pw_hash, salt = hash_password(password)
        user["password_hash"] = pw_hash
        user["salt"] = salt
    users[idx] = user
    save_users(users, path)
    return user


def delete_user(user_id: str, path: Path | None = None) -> None:
    users = load_users(path)
    new_users = [u for u in users if u.get("id") != user_id]
    if len(new_users) == len(users):
        raise KeyError("User not found")
    save_users(new_users, path)


def check_admin_password(password: str) -> bool:
    return secrets.compare_digest(password, ADMIN_PASSWORD)
