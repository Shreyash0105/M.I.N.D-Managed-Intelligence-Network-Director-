import hashlib
import secrets

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.core.security import check_password, ctx, current_user, hash_password, make_token, require_owner
from app.core.util import oid, public, pub_mem, utcnow
from app.db.mongo import db
from app.db.schemas import InviteIn, LoginIn, RegisterIn, TokenIn, WorkspaceIn

router = APIRouter()


def _create_workspace(uid: str, name: str) -> str:
    r = db.workspaces.insert_one({"name": name, "owner_id": uid, "members": [{"user_id": uid, "role": "owner"}],
                                  "settings": {"retention_days": 365, "privacy_mode": "standard"}, "created_at": utcnow()})
    return str(r.inserted_id)


def _workspaces(uid: str):
    out = []
    for w in db.workspaces.find({"members.user_id": uid}):
        ids = [ObjectId(m["user_id"]) for m in w["members"]]
        names = {str(u["_id"]): u for u in db.users.find({"_id": {"$in": ids}})}
        out.append({"id": str(w["_id"]), "name": w["name"],
                    "role": next(m["role"] for m in w["members"] if m["user_id"] == uid),
                    "members": [{"user_id": m["user_id"], "role": m["role"],
                                 "name": names.get(m["user_id"], {}).get("name", "?"),
                                 "email": names.get(m["user_id"], {}).get("email", "")} for m in w["members"]]})
    return out


def _session(u):
    uid = str(u["_id"])
    return {"token": make_token(uid), "user": {"id": uid, "name": u["name"], "email": u["email"]}, "workspaces": _workspaces(uid)}


@router.post("/auth/register")
def register(b: RegisterIn):
    email = b.email.strip().lower()
    if "@" not in email or len(b.password) < 6 or not b.name.strip():
        raise HTTPException(400, "Enter a name, a valid email and a password of 6+ characters")
    try:
        r = db.users.insert_one({"name": b.name.strip(), "email": email, "password_hash": hash_password(b.password),
                                 "created_at": utcnow()})
    except DuplicateKeyError:
        raise HTTPException(409, "That email is already registered")
    uid = str(r.inserted_id)
    _create_workspace(uid, f"{b.name.strip()}'s team")
    return _session({"_id": r.inserted_id, "name": b.name.strip(), "email": email})


@router.post("/auth/login")
def login(b: LoginIn):
    u = db.users.find_one({"email": b.email.strip().lower()})
    if not u or not check_password(b.password, u["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return _session(u)


@router.get("/auth/me")
def me(u=Depends(current_user)):
    s = _session(u)
    return {"user": s["user"], "workspaces": s["workspaces"]}


@router.get("/workspaces")
def list_ws(u=Depends(current_user)):
    return _workspaces(str(u["_id"]))


@router.post("/workspaces")
def create_ws(b: WorkspaceIn, u=Depends(current_user)):
    if not b.name.strip():
        raise HTTPException(400, "Name required")
    return {"id": _create_workspace(str(u["_id"]), b.name.strip())}


@router.post("/workspaces/invite")
def invite(b: InviteIn, c=Depends(ctx)):
    require_owner(c)
    u = db.users.find_one({"email": b.email.strip().lower()})
    if not u:
        raise HTTPException(404, "No account with that email. Ask them to register first.")
    uid = str(u["_id"])
    if any(m["user_id"] == uid for m in c.ws["members"]):
        raise HTTPException(409, "Already a member")
    db.workspaces.update_one({"_id": c.ws["_id"]}, {"$push": {"members": {"user_id": uid, "role": b.role}}})
    return {"ok": True}


# ---- agent tokens for MCP ----
@router.post("/tokens")
def create_token(b: TokenIn, c=Depends(ctx)):
    require_owner(c)
    raw = "tm_" + secrets.token_urlsafe(32)
    db.api_tokens.insert_one({"workspace_id": c.ws_id, "user_id": c.uid, "label": b.label, "scope": b.scope,
                              "token_hash": hashlib.sha256(raw.encode()).hexdigest(), "created_at": utcnow(),
                              "last_used_at": None})
    return {"token": raw, "note": "Copy it now. It is shown only once."}


@router.get("/tokens")
def list_tokens(c=Depends(ctx)):
    return [pub_mem(t) for t in db.api_tokens.find({"workspace_id": c.ws_id}, {"token_hash": 0}).sort("created_at", -1)]


@router.delete("/tokens/{tid}")
def delete_token(tid: str, c=Depends(ctx)):
    require_owner(c)
    db.api_tokens.delete_one({"_id": oid(tid), "workspace_id": c.ws_id})
    return {"ok": True}
