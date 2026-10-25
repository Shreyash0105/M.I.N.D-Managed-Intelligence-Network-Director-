"""Live fan-out (Change Streams -> SSE), audit log and agent run log."""
import logging
import queue
import threading
import time

from app.core.util import utcnow, public
from app.db.mongo import db

log = logging.getLogger("teammind.events")


class Broadcaster:
    """workspace_id -> list of (user_id, Queue). mode: 'change_stream' or 'direct' (no replica set)."""

    def __init__(self):
        self.subs: dict[str, list] = {}
        self.lock = threading.Lock()
        self.mode = "direct"

    def subscribe(self, ws, uid):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.subs.setdefault(ws, []).append((uid, q))
        return q

    def unsubscribe(self, ws, q):
        with self.lock:
            self.subs[ws] = [(u, x) for u, x in self.subs.get(ws, []) if x is not q]

    def send(self, ws, event, to_user=None, private_owner=None):
        event = public({**event, "ts": utcnow()})
        with self.lock:
            targets = list(self.subs.get(ws, []))
        for uid, q in targets:
            if (to_user and uid != to_user) or (private_owner and uid != private_owner):
                continue
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


broadcaster = Broadcaster()


def mem_event(kind, doc):
    return {"kind": kind, "id": str(doc["_id"]), "type": doc.get("type"), "topic": doc.get("topic"),
            "content": (doc.get("content") or "")[:140], "status": doc.get("status"),
            "agent": doc.get("agent_id"), "user_id": doc.get("user_id")}


def notify(ws, kind, doc, force=False):
    """Called by the memory service after a write. When the Change Stream is running it does the job instead."""
    if broadcaster.mode != "direct" and not force:
        return
    owner = doc.get("user_id") if doc.get("scope") == "private" else None
    broadcaster.send(ws, mem_event(kind, doc), private_owner=owner)


def publish_user(ws, uid, event):
    """Private message to one user (e.g. 'Remembered: ...' toast)."""
    broadcaster.send(ws, event, to_user=uid)


def log_event(ws, memory_id, action, actor, reason="", extra=None):
    db.memory_events.insert_one({"workspace_id": ws, "memory_id": str(memory_id), "action": action,
                                 "actor": actor, "reason": reason, "extra": extra or {}, "ts": utcnow()})


def log_run(name, ws, uid, input="", output="", retrieved_ids=None, latency_ms=0, model="", mode="", error=None,
            **extra):
    """extra: conversation_id, thread_id, trace (node-by-node list) ... shown in the Run trace panel."""
    try:
        db.agent_runs.insert_one({"name": name, "workspace_id": ws, "user_id": uid, "input": str(input)[:2000],
                                  "output": str(output)[:2000], "retrieved_ids": retrieved_ids or [],
                                  "latency_ms": int(latency_ms), "model": model, "mode": mode,
                                  "error": error, "ts": utcnow(), **extra})
    except Exception as e:
        log.warning("could not log run: %s", e)


_STATUS_KIND = {"superseded": "superseded", "deleted": "deleted", "archived": "archived", "stale": "stale"}


def _watch():
    fails = 0
    while fails < 3:
        try:
            pipe = [{"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}}]
            with db.memories.watch(pipe, full_document="updateLookup") as stream:
                broadcaster.mode, fails = "change_stream", 0
                log.info("Change Stream running")
                for ch in stream:
                    doc = ch.get("fullDocument") or {}
                    if not doc:
                        continue
                    op = ch["operationType"]
                    if op == "update":
                        keys = set((ch.get("updateDescription") or {}).get("updatedFields", {}).keys())
                        if keys and keys <= {"access_count", "last_accessed_at"}:
                            continue
                    kind = "created" if op == "insert" else _STATUS_KIND.get(doc.get("status"), "updated")
                    owner = doc.get("user_id") if doc.get("scope") == "private" else None
                    broadcaster.send(doc.get("workspace_id"), mem_event(kind, doc), private_owner=owner)
        except Exception as e:
            fails += 1
            broadcaster.mode = "direct"
            log.warning("Change Stream unavailable (%s). Falling back to direct publish.", e)
            time.sleep(3)


def decision_event(row: dict) -> dict:
    """Browser-safe version of a pending-decision row."""
    return {"kind": "needs_user_choice", "id": str(row["_id"]), "thread_id": row["thread_id"],
            "decision_kind": (row.get("payload") or {}).get("kind"), "payload": row.get("payload"),
            "user_id": row.get("user_id")}


def _watch_decisions():
    """Decisions can be opened by another process (the MCP server). Their rows arrive here through a Change Stream."""
    fails = 0
    while fails < 3:
        try:
            pipe = [{"$match": {"operationType": "insert", "fullDocument.action": "needs_user_choice"}}]
            with db.memory_events.watch(pipe) as stream:
                fails = 0
                for ch in stream:
                    row = ch.get("fullDocument") or {}
                    if row:
                        broadcaster.send(row.get("workspace_id"), decision_event(row),
                                         private_owner=row.get("user_id") if row.get("private") else None)
        except Exception as e:
            fails += 1
            log.warning("Decision change stream unavailable (%s)", e)
            time.sleep(3)


def start_change_stream():
    threading.Thread(target=_watch, daemon=True, name="change-stream").start()
    threading.Thread(target=_watch_decisions, daemon=True, name="decision-stream").start()
