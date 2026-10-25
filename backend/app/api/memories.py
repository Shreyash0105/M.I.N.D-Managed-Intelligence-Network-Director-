from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.agents import extractor, guard, reflection
from app.agents.conflict import store_candidate
from app.core.config import settings
from app.core.security import ctx, require_owner, require_write
from app.db.schemas import Candidate, CommitIn, ImportIn, JobIn, MemoryIn, MemoryPatch
from app.services import memory_service as memory

router = APIRouter()


@router.get("/memories")
def list_memories(type: str = "", status: str = "", scope: str = "", tag: str = "", q: str = "", page: int = 1,
                  page_size: int = 50, as_of: str = "", c=Depends(ctx)):
    when = None
    if as_of:
        try:
            when = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "as_of must be an ISO date")
    return memory.list_memories(c.ws_id, c.uid, type or None, status or None, scope or None, tag or None,
                                q or None, page, min(page_size, 200), when)


@router.get("/memories/graph")
def graph(c=Depends(ctx)):
    return memory.graph(c.ws_id, c.uid)


def _answer(run: dict) -> dict:
    """Shape of a Learn-graph run as the REST API has always returned it (+ a pending-decision case)."""
    if run["status"] == "needs_user_choice":
        return {"status": "needs_user_choice", "thread_id": run["thread_id"],
                "message": "I am not sure how this fits with an older memory. Open Decisions to choose.", "results": run["results"]}
    last = run["results"][-1] if run["results"] else {"status": "none", "message": "Nothing was saved."}
    return {**last, "results": run["results"]}


@router.post("/memories")
def create(b: MemoryIn, c=Depends(ctx)):
    require_write(c)
    cand = Candidate(**b.model_dump(), source={"kind": "manual"})
    if not settings.use_langgraph:
        return store_candidate(c.ws_id, c.uid, cand, actor=c.uid)
    from app.graph import runners
    return _answer(runners.start_learn(c.ws_id, c.uid, queue=[cand.model_dump()], actor=c.uid, notify=False, conv_id="manual"))


@router.post("/memories/import")
def import_notes(b: ImportIn, c=Depends(ctx)):
    """Extract candidates from pasted notes. Nothing is saved until the user approves (see /import/commit)."""
    require_write(c)
    cands = extractor.extract(b.text[:8000], "", min_worthiness=0.5)
    out = []
    for cand in cands:
        g = guard.check(cand.content)
        out.append({**cand.model_dump(), "content": g["clean_text"], "guard": g["findings"], "blocked": g["action"] == "block"})
    return {"items": out}


@router.post("/memories/import/commit")
def commit(b: CommitIn, c=Depends(ctx)):
    require_write(c)
    items = b.items[:50]
    for cand in items:
        cand.source = {"kind": "import"}
    if not settings.use_langgraph:
        return {"results": [store_candidate(c.ws_id, c.uid, cand, actor=c.uid) for cand in items]}
    from app.graph import runners
    run = runners.start_learn(c.ws_id, c.uid, queue=[x.model_dump() for x in items], actor=c.uid, notify=False,
                              conv_id="import", max_candidates=len(items))
    return {"results": run["results"], "status": run["status"], "pending": run.get("pending", []), "thread_id": run["thread_id"]}


@router.post("/memories/consolidate")
def consolidate(b: JobIn = JobIn(), c=Depends(ctx)):
    require_write(c)
    if not settings.use_langgraph:
        return reflection.run(c.ws_id, c.uid)
    from app.graph import runners
    return runners.run_reflection(c.ws_id, c.uid, require_approval=b.require_approval)


@router.get("/memories/{mid}")
def get_one(mid: str, c=Depends(ctx)):
    return memory.get(c.ws_id, c.uid, mid)


@router.patch("/memories/{mid}")
def patch(mid: str, b: MemoryPatch, c=Depends(ctx)):
    require_write(c)
    if b.pinned is not None:
        memory.set_pinned(c.ws_id, c.uid, mid, b.pinned)
    if b.content:
        g = guard.check(b.content)
        if g["action"] == "block":
            raise HTTPException(400, f"That text contains a secret ({', '.join(g['findings'])}) and was not saved")
        if not settings.use_langgraph:
            new = memory.correct(c.ws_id, c.uid, mid, g["clean_text"], b.reason, actor=c.uid)
            return {"id": str(new["_id"]), "status": "superseded"}
        from app.graph import runners
        memory.get(c.ws_id, c.uid, mid)  # 404 early if it is not visible to this user
        run = runners.start_learn(c.ws_id, c.uid, force={"target_id": mid, "content": g["clean_text"], "reason": b.reason},
                                  actor=c.uid, notify=False, conv_id="manual")
        r = run["results"][-1] if run["results"] else {}
        if r.get("status") == "error":
            raise HTTPException(400, r.get("message", "Could not correct"))
        return {"id": r.get("id"), "status": "superseded"}
    return {"id": mid}


@router.delete("/memories/{mid}")
def delete(mid: str, hard: bool = False, c=Depends(ctx)):
    require_write(c)
    if hard:
        require_owner(c)
        memory.hard_delete(c.ws_id, c.uid, mid, actor=c.uid)
    else:
        memory.soft_delete(c.ws_id, c.uid, mid, actor=c.uid)
    return {"ok": True}


@router.post("/memories/{mid}/restore")
def restore(mid: str, c=Depends(ctx)):
    require_write(c)
    memory.restore(c.ws_id, c.uid, mid, actor=c.uid)
    return {"ok": True}


@router.get("/memories/{mid}/lineage")
def lineage(mid: str, c=Depends(ctx)):
    return memory.lineage(c.ws_id, c.uid, mid)


@router.get("/memories/{mid}/events")
def events(mid: str, c=Depends(ctx)):
    return {"items": memory.events(c.ws_id, c.uid, mid)}
