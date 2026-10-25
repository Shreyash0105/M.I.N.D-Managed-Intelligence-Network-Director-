import time
from collections import defaultdict, deque
from datetime import timedelta

import bcrypt
import jwt
from bson import ObjectId
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.util import utcnow
from app.db.mongo import db

bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_token(uid: str) -> str:
    exp = utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": uid, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not cred:
        raise HTTPException(401, "Not logged in")
    try:
        data = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])
        user = db.users.find_one({"_id": ObjectId(data["sub"])})
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


class Ctx:
    """Who is calling, and for which workspace. Always built on the server, never from the request body."""

    def __init__(self, user, ws, role):
        self.user, self.ws, self.role = user, ws, role
        self.uid = str(user["_id"])
        self.ws_id = str(ws["_id"])

    @property
    def can_write(self):
        return self.role in ("owner", "member")


def ctx(user=Depends(current_user), x_workspace: str = Header(...)) -> Ctx:
    try:
        ws = db.workspaces.find_one({"_id": ObjectId(x_workspace), "members.user_id": str(user["_id"])})
    except Exception:
        ws = None
    if not ws:
        raise HTTPException(403, "Not a member of this workspace")
    role = next(m["role"] for m in ws["members"] if m["user_id"] == str(user["_id"]))
    return Ctx(user, ws, role)


def require_write(c: Ctx):
    if not c.can_write:
        raise HTTPException(403, "Viewers have read-only access")


def require_owner(c: Ctx):
    if c.role != "owner":
        raise HTTPException(403, "Only the workspace owner can do this")


_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str):
    q, t = _hits[key], time.time()
    while q and q[0] < t - 60:
        q.popleft()
    if len(q) >= settings.rate_limit_per_min:
        raise HTTPException(429, "Too many requests, slow down a little")
    q.append(t)
