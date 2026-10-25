from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.security import ctx, require_owner
from app.core.util import pub_mem, utcnow
from app.db import indexes
from app.db.mongo import client, db
from app.db.schemas import DemoModeIn, JobIn
from app.services import memory_service as memory, retrieval_service, seed
from app.services.events_service import broadcaster
from app.workers import scheduler

router = APIRouter()


@router.get("/admin/health")
def health(c=Depends(ctx)):
    try:
        client.admin.command("ping")
        mongo = "ok"
    except Exception as e:
        mongo = f"error: {e}"
    graphs = {"enabled": settings.use_langgraph}
    if settings.use_langgraph:
        from app.graph import registry
        graphs.update(compiled=list(registry.GRAPHS), checkpointer=registry.checkpointer_kind)
    flags = {"ask_on_conflict": False}
    if settings.use_langgraph:
        from app.graph import runners
        flags = runners.workspace_flags(c.ws_id)
    return {"mongo": mongo, "indexes": indexes.index_status(), "llm_provider": settings.llm_provider,
            "graphs": graphs, "demo_mode": flags,
            "pending_decisions": db.memory_events.count_documents({"workspace_id": c.ws_id, "action": "needs_user_choice", "resolved": False}),
            "model_main": settings.llm_model_main, "model_fast": settings.llm_model_fast,
            "embedding_backend": settings.embedding_backend, "live_mode": broadcaster.mode,
            "rerank_enabled": settings.rerank_enabled, "last_retrieval": retrieval_service.status_info,
            "jobs": [pub_mem(j) for j in db.jobs.find()]}


@router.post("/admin/jobs/{name}")
def run_job(name: str, b: JobIn = JobIn(), c=Depends(ctx)):
    require_owner(c)
    if name == "freshness":
        return scheduler.run_job("freshness", days_ahead=b.days_ahead, ws=c.ws_id, dry_run=b.dry_run)
    if name == "reflection":
        return scheduler.run_job("reflection", ws=c.ws_id, uid=c.uid, require_approval=b.require_approval)
    raise HTTPException(404, "Unknown job")


@router.get("/admin/graphs")
def graphs(c=Depends(ctx)):
    """Mermaid text of every compiled graph (also handy for slides)."""
    require_owner(c)
    if not settings.use_langgraph:
        raise HTTPException(404, "LangGraph is switched off (USE_LANGGRAPH=false)")
    from app.graph import registry
    return {"graphs": registry.mermaid(), "checkpointer": registry.checkpointer_kind}


@router.post("/admin/demo-mode")
def demo_mode(b: DemoModeIn, c=Depends(ctx)):
    """Demo helper: when on, the Learn graph always asks a human about contradictions (a real LLM is not 'unsure' on cue)."""
    require_owner(c)
    db.workspaces.update_one({"_id": c.ws["_id"]}, {"$set": {"settings.demo_ask_on_conflict": b.ask_on_conflict}})
    return {"ask_on_conflict": b.ask_on_conflict}


@router.post("/admin/seed")
def seed_demo(c=Depends(ctx)):
    require_owner(c)
    return seed.seed_workspace(c.ws_id, c.uid)


@router.get("/analytics/summary")
def summary(c=Depends(ctx)):
    ws, uid = c.ws_id, c.uid
    vis = memory.visible_filter(ws, uid)
    by_type = {r["_id"]: r["n"] for r in db.memories.aggregate(
        [{"$match": {**vis, "status": "active"}}, {"$group": {"_id": "$type", "n": {"$sum": 1}}}])}
    by_status = {r["_id"]: r["n"] for r in db.memories.aggregate(
        [{"$match": vis}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    top = [pub_mem(d) for d in db.memories.find({**vis, "access_count": {"$gt": 0}}, {"embedding": 0})
           .sort("access_count", -1).limit(5)]
    modes = {r["_id"]: r["n"] for r in db.agent_runs.aggregate(
        [{"$match": {"workspace_id": ws, "name": "chat", "mode": {"$ne": ""}}}, {"$group": {"_id": "$mode", "n": {"$sum": 1}}}])}
    lat = list(db.agent_runs.aggregate(
        [{"$match": {"workspace_id": ws, "name": "chat"}}, {"$group": {"_id": None, "avg": {"$avg": "$latency_ms"}, "n": {"$sum": 1}}}]))
    day = utcnow() - timedelta(days=1)
    node_latency = [{"node": r["_id"], "avg_ms": round(r["avg"]), "runs": r["n"]} for r in db.agent_runs.aggregate([
        {"$match": {"workspace_id": ws, "name": "chat", "trace": {"$exists": True}}}, {"$unwind": "$trace"},
        {"$match": {"trace.ms": {"$exists": True}}},
        {"$group": {"_id": "$trace.node", "avg": {"$avg": "$trace.ms"}, "n": {"$sum": 1}}}, {"$sort": {"avg": -1}}])]
    return {"node_latency": node_latency, "by_type": by_type, "by_status": by_status, "top_used": top, "retrieval_modes": modes,
            "avg_latency_ms": round(lat[0]["avg"]) if lat else 0, "chat_turns": lat[0]["n"] if lat else 0,
            "events_24h": db.memory_events.count_documents({"workspace_id": ws, "ts": {"$gte": day}}),
            "expiring": db.memories.count_documents({**vis, "status": "active", "expires_at": {"$ne": None}}),
            "flagged": db.memories.count_documents({**vis, "flags": {"$exists": True, "$ne": []}})}
