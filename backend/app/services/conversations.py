from app.core.util import oid, pub_mem, utcnow
from app.db.mongo import db


def ensure(ws, uid, cid, title):
    if cid:
        c = db.conversations.find_one({"_id": oid(cid), "workspace_id": ws, "user_id": uid})
        if c:
            return str(c["_id"])
    r = db.conversations.insert_one({"workspace_id": ws, "user_id": uid, "title": title[:60], "messages": [],
                                     "created_at": utcnow(), "updated_at": utcnow()})
    return str(r.inserted_id)


def last_turns(cid, n=3):
    c = db.conversations.find_one({"_id": oid(cid)}, {"messages": {"$slice": -2 * n}})
    return [{"role": m["role"], "text": m["text"]} for m in (c or {}).get("messages", [])]


def append(cid, user_text, answer, used_ids, mem_brief):
    t = utcnow()
    db.conversations.update_one({"_id": oid(cid)}, {
        "$push": {"messages": {"$each": [
            {"role": "user", "text": user_text, "ts": t},
            {"role": "assistant", "text": answer, "used_memory_ids": used_ids, "memories": mem_brief, "ts": t}]}},
        "$set": {"updated_at": t}})


def list_for(ws, uid, limit=30):
    cur = db.conversations.find({"workspace_id": ws, "user_id": uid}, {"messages": 0}).sort("updated_at", -1).limit(limit)
    return [pub_mem(c) for c in cur]


def get(ws, uid, cid):
    c = db.conversations.find_one({"_id": oid(cid), "workspace_id": ws, "user_id": uid})
    return pub_mem(c) if c else None
