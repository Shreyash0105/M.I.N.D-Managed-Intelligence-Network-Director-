"""The ONLY module that writes to the memories collection."""
import re
from datetime import timedelta

from fastapi import HTTPException
from pymongo.errors import ConfigurationError, OperationFailure

from app.agents import guard
from app.core.config import settings
from app.core.util import oid, pub_mem, utcnow
from app.db.mongo import client, db
from app.services import events_service as ev
from app.services.embeddings import embed, memory_text


def visible_filter(ws, uid):
    """Everything in this workspace except other people's private memories."""
    return {"workspace_id": ws, "$or": [{"scope": {"$ne": "private"}}, {"user_id": uid}]}


def _find(ws, uid, mid, with_embedding=False):
    d = db.memories.find_one({"_id": oid(mid), **visible_filter(ws, uid)}, None if with_embedding else {"embedding": 0})
    if not d:
        raise HTTPException(404, "Memory not found")
    return d


def build_doc(ws, uid, d: dict) -> dict:
    t = d.get("created_at") or utcnow()
    days = d.get("expires_in_days")
    expires = d.get("expires_at") or (t + timedelta(days=float(days)) if days else None)
    flags = list(d.get("flags", []))
    if guard.scan_injection(d["content"]) and "injection" not in flags:
        flags.append("injection")  # kept for audit, never sent to the Responder
    doc = {
        "workspace_id": ws, "user_id": uid, "agent_id": d.get("agent_id"),
        "type": d.get("type", "fact"), "scope": d.get("scope", "workspace"),
        "topic": d.get("topic") or "general", "content": d["content"].strip(),
        "tags": d.get("tags", []), "entities": d.get("entities", []),
        "importance": d.get("importance", 0.6), "confidence": d.get("confidence", 0.8),
        "reinforcement_count": 0, "access_count": 0, "last_accessed_at": None,
        "status": "active", "pinned": bool(d.get("pinned", False)), "flags": flags,
        "supersedes": None, "superseded_by": None, "derived_from": d.get("derived_from", []),
        "valid_from": t, "valid_until": d.get("valid_until"), "expires_at": expires,
        "source": d.get("source") or {"kind": "manual"},
        "created_at": t, "updated_at": t,
    }
    doc["embedding"] = embed(memory_text(doc))
    doc["embedding_model"] = settings.embedding_model if settings.embedding_backend == "local" else "hash"
    return doc


def create_memory(ws, uid, data: dict, actor="user", reason="created") -> dict:
    doc = build_doc(ws, uid, data)
    db.memories.insert_one(doc)
    ev.log_event(ws, doc["_id"], "created", actor, reason)
    ev.notify(ws, "created", doc)
    return doc


def _txn(fn):
    """Run fn(session) in a transaction; fall back to plain writes on servers without transactions."""
    try:
        with client.start_session() as s:
            with s.start_transaction():
                fn(s)
    except (OperationFailure, ConfigurationError):
        fn(None)


def supersede(ws, uid, old_id, new_data: dict, actor: str, reason: str) -> dict:
    old = _find(ws, uid, old_id)
    new = build_doc(ws, uid, new_data)
    new["supersedes"] = old["_id"]
    t = utcnow()

    def work(s):
        db.memories.insert_one(new, session=s)
        db.memories.update_one({"_id": old["_id"], "workspace_id": ws},
                               {"$set": {"status": "superseded", "superseded_by": new["_id"],
                                         "superseded_at": t, "updated_at": t}}, session=s)
        db.memory_events.insert_many([
            {"workspace_id": ws, "memory_id": str(old["_id"]), "action": "superseded", "actor": actor,
             "reason": reason, "extra": {"by": str(new["_id"])}, "ts": t},
            {"workspace_id": ws, "memory_id": str(new["_id"]), "action": "created", "actor": actor,
             "reason": f"supersedes {old['_id']}: {reason}", "extra": {}, "ts": t}], session=s)

    _txn(work)
    old.update(status="superseded")
    ev.notify(ws, "superseded", old)
    ev.notify(ws, "created", new)
    return new


def correct(ws, uid, mid, new_content, reason="manual correction", actor="user") -> dict:
    old = _find(ws, uid, mid)
    keep = {k: old.get(k) for k in ("type", "topic", "tags", "entities", "importance", "scope", "agent_id", "expires_at")}
    return supersede(ws, uid, mid, {**keep, "content": new_content, "confidence": 0.95,
                                    "source": {"kind": "correction", "of": str(old["_id"])}}, actor, reason)


def reinforce(ws, mid):
    db.memories.update_one({"_id": oid(mid), "workspace_id": ws}, [{"$set": {
        "reinforcement_count": {"$add": [{"$ifNull": ["$reinforcement_count", 0]}, 1]},
        "confidence": {"$min": [1, {"$add": [{"$ifNull": ["$confidence", 0.8]}, 0.03]}]},
        "updated_at": utcnow()}}])
    ev.log_event(ws, mid, "reinforced", "agent", "seen again")


def soft_delete(ws, uid, mid, actor="user", reason="") -> dict:
    d = _find(ws, uid, mid)
    t = utcnow()
    db.memories.update_one({"_id": d["_id"], "workspace_id": ws},
                           {"$set": {"status": "deleted", "deleted_at": t, "updated_at": t}})
    ev.log_event(ws, d["_id"], "deleted", actor, reason or "soft delete")
    d["status"] = "deleted"
    ev.notify(ws, "deleted", d)
    return d


def restore(ws, uid, mid, actor="user") -> dict:
    d = _find(ws, uid, mid)
    db.memories.update_one({"_id": d["_id"], "workspace_id": ws},
                           {"$set": {"status": "active", "updated_at": utcnow()},
                            "$unset": {"deleted_at": "", "superseded_by": "", "superseded_at": ""}})
    ev.log_event(ws, d["_id"], "restored", actor, "")
    d["status"] = "active"
    ev.notify(ws, "updated", d)
    return d


def hard_delete(ws, uid, mid, actor="user", reason=""):
    d = _find(ws, uid, mid)
    db.memories.delete_one({"_id": d["_id"], "workspace_id": ws})
    ev.log_event(ws, d["_id"], "purged", actor, reason or "hard delete")  # no content kept in the audit trail
    ev.broadcaster.send(ws, {"kind": "purged", "id": str(d["_id"]), "type": d.get("type"), "topic": d.get("topic")},
                        private_owner=d.get("user_id") if d.get("scope") == "private" else None)


def set_status(ws, mid, status: str, reason: str, actor: str, when=None):
    """Freshness Keeper: archived / stale. Always scoped by workspace."""
    t = when or utcnow()
    d = db.memories.find_one_and_update(
        {"_id": oid(mid), "workspace_id": ws},
        {"$set": {"status": status, "status_reason": reason, "status_changed_at": t}},
        projection={"embedding": 0}, return_document=True)
    if d:
        ev.log_event(ws, d["_id"], status, actor, reason)
        ev.notify(ws, status, d)
    return d


def lower_importance(ws, ids, factor=0.8):
    """Reflection: after a lesson is derived, its source memories rank a little lower."""
    db.memories.update_many({"_id": {"$in": [oid(i) for i in ids]}, "workspace_id": ws}, {"$mul": {"importance": factor}})


def set_pinned(ws, uid, mid, pinned: bool):
    d = _find(ws, uid, mid)
    db.memories.update_one({"_id": d["_id"], "workspace_id": ws}, {"$set": {"pinned": pinned, "updated_at": utcnow()}})
    ev.log_event(ws, d["_id"], "pinned" if pinned else "unpinned", "user")


def get(ws, uid, mid) -> dict:
    return pub_mem(_find(ws, uid, mid))


def list_memories(ws, uid, type=None, status=None, scope=None, tag=None, q=None, page=1, page_size=50, as_of=None):
    f = visible_filter(ws, uid)
    and_ = []
    if type:
        f["type"] = type
    if scope:
        f["scope"] = scope
    if tag:
        f["tags"] = tag
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        and_.append({"$or": [{"content": rx}, {"topic": rx}, {"tags": rx}]})
    if as_of:  # time travel: what did the team know on that day?
        and_ += [{"created_at": {"$lte": as_of}},
                 {"$or": [{"superseded_at": None}, {"superseded_at": {"$gt": as_of}}]},
                 {"$or": [{"deleted_at": None}, {"deleted_at": {"$gt": as_of}}]},
                 {"$or": [{"expires_at": None}, {"expires_at": {"$gt": as_of}}]}]
    elif status and status != "all":
        f["status"] = status
    else:
        f["status"] = {"$ne": "deleted"}
    if and_:
        f["$and"] = and_
    total = db.memories.count_documents(f)
    cur = (db.memories.find(f, {"embedding": 0}).sort("updated_at", -1)
           .skip((max(page, 1) - 1) * page_size).limit(page_size))
    return {"items": [pub_mem(d) for d in cur], "total": total, "page": page}


def lineage(ws, uid, mid) -> dict:
    d = _find(ws, uid, mid)
    chain, seen, cur = [d], {d["_id"]}, d
    while cur.get("supersedes") and cur["supersedes"] not in seen:
        nxt = db.memories.find_one({"_id": cur["supersedes"], "workspace_id": ws}, {"embedding": 0})
        if not nxt:
            break
        chain.insert(0, nxt); seen.add(nxt["_id"]); cur = nxt
    cur = d
    while cur.get("superseded_by") and cur["superseded_by"] not in seen:
        nxt = db.memories.find_one({"_id": cur["superseded_by"], "workspace_id": ws}, {"embedding": 0})
        if not nxt:
            break
        chain.append(nxt); seen.add(nxt["_id"]); cur = nxt
    src = list(db.memories.find({"_id": {"$in": d.get("derived_from", [])}, "workspace_id": ws}, {"embedding": 0}))
    der = list(db.memories.find({"derived_from": d["_id"], "workspace_id": ws}, {"embedding": 0}))
    return {"versions": [pub_mem(x) for x in chain], "sources": [pub_mem(x) for x in src],
            "derived": [pub_mem(x) for x in der]}


def events(ws, uid, mid, limit=50):
    d = _find(ws, uid, mid)
    cur = db.memory_events.find({"workspace_id": ws, "memory_id": str(d["_id"])}).sort("ts", -1).limit(limit)
    return [pub_mem(x) for x in cur]


def graph(ws, uid, limit=400):
    docs = list(db.memories.find({**visible_filter(ws, uid), "status": {"$ne": "deleted"}}, {"embedding": 0})
                .sort("updated_at", -1).limit(limit))
    ids = {d["_id"] for d in docs}
    edges, by_tag = [], {}
    for d in docs:
        if d.get("supersedes") in ids:
            edges.append({"source": str(d["supersedes"]), "target": str(d["_id"]), "kind": "supersedes"})
        for s in d.get("derived_from", []):
            if s in ids:
                edges.append({"source": str(s), "target": str(d["_id"]), "kind": "derived"})
        for t in d.get("tags", []):
            by_tag.setdefault(t, []).append(str(d["_id"]))
    for t, lst in by_tag.items():
        for a, b in zip(lst, lst[1:]):
            edges.append({"source": a, "target": b, "kind": "tag", "tag": t})
    return {"nodes": [pub_mem(d) for d in docs], "edges": edges}
