"""Bearer tokens: $DATA_DIR/api/tokens.json = {token: {name, role}}.

The file is re-read when it changes, so `python -m s2d.api token ...` works without a restart.
With API_PUBLIC_ROLE set, a request without a token is user "public" with that role.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import store

ROLES = ("student", "teacher", "admin")
PUBLIC_USER = "public"
_bearer = HTTPBearer(auto_error=False, description="token from `python -m s2d.api token <name> <role>`")
_cache: dict = {"mtime": None, "tokens": {}}


@dataclass(frozen=True)
class User:
    name: str
    role: str

    @property
    def staff(self) -> bool:
        return self.role in ("teacher", "admin")


def tokens_path():
    return store.api_dir() / "tokens.json"


def tokens() -> dict:
    p = tokens_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    if mtime != _cache["mtime"]:
        _cache.update(mtime=mtime, tokens=store.read_json(p) or {})
    return _cache["tokens"]


def add_token(name: str, role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    tok = secrets.token_urlsafe(24)
    t = dict(store.read_json(tokens_path()) or {})
    t[tok] = {"name": name, "role": role}
    store.write_json(tokens_path(), t)
    return tok


def public_role() -> str | None:
    """API_PUBLIC_ROLE=student|teacher|admin lets requests without a token in as user "public"."""
    role = os.environ.get("API_PUBLIC_ROLE", "").strip()
    if role and role not in ROLES:
        raise RuntimeError(f"API_PUBLIC_ROLE must be one of {', '.join(ROLES)}, not {role!r}")
    return role or None


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if cred is None and (role := public_role()):
        return User(PUBLIC_USER, role)
    entry = tokens().get(cred.credentials) if cred else None
    if not entry or entry.get("role") not in ROLES:
        # an unknown token stays 401 even in public mode, so a client can drop a stale one
        raise HTTPException(401, "missing or unknown token", headers={"WWW-Authenticate": "Bearer"})
    return User(entry.get("name", "?"), entry["role"])


def staff_user(user: User = Depends(current_user)) -> User:
    if not user.staff:
        raise HTTPException(403, "teacher or admin only")
    return user
