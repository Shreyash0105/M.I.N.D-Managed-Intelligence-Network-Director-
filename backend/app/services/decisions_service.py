"""Pending human decisions (the Decision inbox).

When a graph calls interrupt(), LangGraph saves the whole run in MongoDB under its thread_id. We also write one
row to memory_events (action = needs_user_choice) so the question survives a page refresh and shows in the inbox.
A row that is `private` (it quotes a private memory) is only visible to the user whose run it is."""
from app.core.util import oid, utcnow
from app.db.mongo import db
from app.services import events_service as ev

ACTION = "needs_user_choice"
CHOICES = {"conflict": ("use_new", "keep_old", "keep_both"), "lesson": ("approve", "reject")}


def open_decision(ws: str, uid: str, thread_id: str, payload: dict, private: bool = False) -> dict:
    row = {"workspace_id": ws, "memory_id": "", "action": ACTION, "actor": uid, "user_id": uid, "private": private,
           "reason": str(payload.get("question") or payload.get("kind") or "")[:200], "thread_id": thread_id,
           "payload": payload, "resolved": False, "extra": {}, "ts": utcnow()}
    row["_id"] = db.memory_events.insert_one(row).inserted_id
    if ev.broadcaster.mode == "direct":  # with a Change Stream running, it announces the row (also for other processes)
        ev.broadcaster.send(ws, ev.decision_event(row), private_owner=uid if private else None)
    return row


def visible(ws: str, uid: str) -> dict:
    return {"workspace_id": ws, "action": ACTION, "resolved": False, "$or": [{"private": {"$ne": True}}, {"user_id": uid}]}


def pending(ws: str, uid: str) -> list[dict]:
    return list(db.memory_events.find(visible(ws, uid)).sort("ts", 1))


def claim(ws: str, uid: str, thread_id: str):
    """Atomically take the oldest open question of a thread, so a double click cannot resume twice."""
    return db.memory_events.find_one_and_update(
        {**visible(ws, uid), "thread_id": thread_id}, {"$set": {"resolved": True, "resolved_at": utcnow(), "resolved_by": uid}},
        sort=[("ts", 1)])


def release(row_id):
    db.memory_events.update_one({"_id": oid(row_id)}, {"$set": {"resolved": False}, "$unset": {"resolved_at": "", "resolved_by": ""}})


def announce_resolved(ws: str, thread_id: str, choice: str):
    ev.broadcaster.send(ws, {"kind": "decision_resolved", "thread_id": thread_id, "choice": choice})
