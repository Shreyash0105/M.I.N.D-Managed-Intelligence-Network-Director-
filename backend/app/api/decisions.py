"""Decision inbox: questions that paused a graph (interrupt) and wait for a human."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import ctx, require_write
from app.core.util import public
from app.db.schemas import ResumeIn
from app.graph import threads
from app.services import decisions_service as decisions

router = APIRouter()


@router.get("/decisions/pending")
def pending(c=Depends(ctx)):
    return {"items": [public({"id": r["_id"], "thread_id": r["thread_id"], "payload": r.get("payload"), "ts": r["ts"],
                              "private": bool(r.get("private"))}) for r in decisions.pending(c.ws_id, c.uid)]}


@router.post("/decisions/{thread_id}/resume")
def resume(thread_id: str, body: ResumeIn, c=Depends(ctx)):
    from app.graph import runners
    require_write(c)
    if threads.kind_of(thread_id) not in ("learn", "reflect") or not threads.belongs_to(c.ws_id, thread_id):
        raise HTTPException(403, "Not your workspace")  # the thread name carries its workspace
    row = decisions.claim(c.ws_id, c.uid, thread_id)
    if not row:
        raise HTTPException(404, "No open question for this thread (already answered?)")
    kind = (row.get("payload") or {}).get("kind", "conflict")
    if body.choice not in decisions.CHOICES.get(kind, ()):
        decisions.release(row["_id"])
        raise HTTPException(422, "Unknown choice")
    try:
        res = runners.resume(c.ws_id, row.get("user_id") or c.uid, thread_id, body.choice)  # runs as the user whose run it is
    except Exception:
        decisions.release(row["_id"])  # keep the question open if the resume failed
        raise
    decisions.announce_resolved(c.ws_id, thread_id, body.choice)
    return {"ok": True, "status": res["status"], "results": res.get("results", []), "pending": res.get("pending", [])}
