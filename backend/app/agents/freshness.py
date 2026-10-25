"""Agent 8: Freshness Keeper. Decay -> archive, LLM staleness check, purge old soft-deletes, purge old graph threads.
Four independent jobs (plain functions). graph/fresh_nodes.py runs them in parallel; run() composes them without LangGraph."""
import math
from datetime import timedelta

from app.core.config import settings
from app.core.util import utcnow
from app.db.mongo import db
from app.llm import provider as llm, prompts
from app.services import events_service as ev
from app.services import memory_service as memory

DECAY_TYPES = {"preference", "feedback", "outcome", "fact", "episode"}  # decisions/constraints never decay
MAX_LLM_CHECKS = 8
PURGE_AFTER_DAYS = 30
EPHEMERAL_THREAD_HOURS = 1  # Compare-view threads are throw-away


def _t(days_ahead: int):
    return utcnow() + timedelta(days=days_ahead)  # days_ahead = "time machine" for demos


def _query(ws, statuses):
    q = {"status": {"$in": statuses}}
    if ws:
        q["workspace_id"] = ws
    return q


def archive_reason(d: dict, t, days_ahead: int) -> str | None:
    """Why this memory should be archived at time t, or None. Shared by decay_archive and stale_flag so the two parallel
    jobs never touch the same memory."""
    if d.get("pinned"):
        return None
    if days_ahead > 0 and d.get("expires_at") and d["expires_at"] <= t:
        return "expired (simulated)"
    if d["type"] in DECAY_TYPES and d["status"] == "active":
        age = max(0.0, (t - d["updated_at"]).total_seconds() / 86400)
        decay = d.get("importance", 0.5) * math.exp(-age / settings.decay_half_life_days) + 0.1 * math.log(1 + d.get("access_count", 0))
        if decay < settings.archive_threshold:
            return f"decayed (score {decay:.2f})"
    return None


def _row(d, to, reason):
    return {"id": str(d["_id"]), "topic": d.get("topic"), "content": d["content"][:80], "to": to, "reason": reason}


def _apply(d, new, reason, t, dry_run):
    if not dry_run:
        memory.set_status(d["workspace_id"], d["_id"], new, reason, "freshness-keeper", when=t)


def decay_archive(ws=None, days_ahead=0, dry_run=False) -> dict:
    t, out = _t(days_ahead), []
    for d in db.memories.find(_query(ws, ["active", "stale"]), {"embedding": 0}):
        reason = archive_reason(d, t, days_ahead)
        if reason:
            out.append(_row(d, "archived", reason))
            _apply(d, "archived", reason, t, dry_run)
    return {"changes": out}


def stale_flag(ws=None, days_ahead=0, dry_run=False) -> dict:
    t, out, checks = _t(days_ahead), [], 0
    for d in db.memories.find({**_query(ws, ["active"]), "type": {"$in": ["fact", "outcome"]}}, {"embedding": 0}):
        if d.get("pinned") or archive_reason(d, t, days_ahead):
            continue
        age = max(0.0, (t - d["updated_at"]).total_seconds() / 86400)
        if age < settings.stale_days or checks >= MAX_LLM_CHECKS:
            continue
        checks += 1
        r = llm.complete_json(prompts.STALE, f'Memory: "{d["content"]}"\nType: {d["type"]}\nAge in days: {age:.0f}',
                              settings.llm_model_fast, task="stale", fake={"age_days": age}, max_tokens=300)
        if isinstance(r, dict) and r.get("stale") is True:
            reason = str(r.get("reason", "judged out of date"))[:200]
            out.append(_row(d, "stale", reason))
            _apply(d, "stale", reason, t, dry_run)
    return {"changes": out, "llm_checks": checks}


def purge_deleted(ws=None, days_ahead=0, dry_run=False) -> dict:
    t = _t(days_ahead)
    q = {"status": "deleted", "deleted_at": {"$lt": t - timedelta(days=PURGE_AFTER_DAYS)}}
    if ws:
        q["workspace_id"] = ws
    old = list(db.memories.find(q, {"_id": 1, "workspace_id": 1}))
    if not dry_run:
        for d in old:
            db.memories.delete_one({"_id": d["_id"]})
            ev.log_event(d["workspace_id"], d["_id"], "purged", "freshness-keeper", "grace period over")  # id only, never text
    return {"purged": len(old)}


def purge_threads(ws=None, days_ahead=0, dry_run=False, checkpointer=None) -> dict:
    """Delete finished graph threads (checkpoints) older than the retention setting, so deleted text does not
    linger in graph history. Threads that wait for a human are never purged."""
    t = _t(days_ahead)
    q = {"pending": {"$ne": True}, "$or": [
        {"ephemeral": True, "updated_at": {"$lt": t - timedelta(hours=EPHEMERAL_THREAD_HOURS)}},
        {"updated_at": {"$lt": t - timedelta(days=settings.thread_retention_days)}}]}
    if ws:
        q["workspace_id"] = ws
    old = [x["_id"] for x in db.graph_threads.find(q, {"_id": 1})]
    if not dry_run and old:
        if checkpointer is None:
            from app.graph.registry import checkpointer as cp
            checkpointer = cp
        for tid in old:
            try:
                checkpointer.delete_thread(tid)
            except Exception:
                continue
        db.graph_threads.delete_many({"_id": {"$in": old}})
    return {"threads_purged": len(old)}


def combine(parts: list[dict], days_ahead: int, dry_run: bool) -> dict:
    """Merge the four job results into the shape the UI already shows."""
    out = {"llm_checks": 0, "changes": [], "purged": 0, "threads_purged": 0}
    for p in parts:
        out["changes"] += p.get("changes", [])
        out["llm_checks"] += p.get("llm_checks", 0)
        out["purged"] += p.get("purged", 0)
        out["threads_purged"] += p.get("threads_purged", 0)
    out.update(dry_run=dry_run, as_of=_t(days_ahead).isoformat())
    return out


def run(days_ahead: int = 0, ws: str | None = None, dry_run: bool = False) -> dict:
    """Plain (no graph) version: used when USE_LANGGRAPH=false."""
    parts = [decay_archive(ws, days_ahead, dry_run), stale_flag(ws, days_ahead, dry_run), purge_deleted(ws, days_ahead, dry_run)]
    return combine(parts, days_ahead, dry_run)
