from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException


def utcnow():
    return datetime.now(timezone.utc)


def oid(s) -> ObjectId:
    try:
        return ObjectId(str(s))
    except Exception:
        raise HTTPException(400, "Invalid id")


def public(o):
    """Make Mongo documents JSON-safe. Never leaks embeddings or password hashes."""
    if isinstance(o, dict):
        return {k: public(v) for k, v in o.items() if k not in ("embedding", "password_hash", "token_hash")}
    if isinstance(o, (list, tuple)):
        return [public(x) for x in o]
    if isinstance(o, ObjectId):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    return o


def pub_mem(d: dict) -> dict:
    out = public(d)
    out["id"] = out.pop("_id", None)
    return out


def age_str(dt) -> str:
    if not dt:
        return "never"
    if isinstance(dt, str):  # graph state keeps datetimes as ISO strings
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return "unknown"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    s = (utcnow() - dt).total_seconds()
    if s < 3600:
        return f"{max(1, int(s // 60))}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"
