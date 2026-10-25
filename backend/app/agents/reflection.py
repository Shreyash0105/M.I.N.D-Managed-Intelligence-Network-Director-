"""Agent 7: Reflection. Merges many small memories on one topic into one higher-level strategy memory.
Plain, testable functions; graph/reflect_nodes.py wraps them (retry loop + optional human approval)."""
from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.core.config import settings
from app.core.util import oid
from app.db.mongo import db
from app.llm import provider as llm, prompts
from app.services import memory_service as memory


class LessonOut(BaseModel):
    content: str
    confidence: float = 0.65
    tags: List[str] = ["lesson"]

    @field_validator("content", mode="before")
    @classmethod
    def _content(cls, v):
        v = str(v or "").strip()
        if len(v) < 8:
            raise ValueError("lesson too short")
        return v

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        try:
            return max(0.0, min(0.7, float(v)))  # lessons are guesses until a human approves
        except (TypeError, ValueError):
            return 0.6

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, v):
        return [str(t).lower() for t in v][:6] if isinstance(v, list) and v else ["lesson"]


def select_groups(ws: str, min_group: int | None = None, max_groups: int = 3) -> list[dict]:
    """Topics with enough small memories, skipping topics that already have a strategy. JSON-safe (string ids)."""
    n = min_group or settings.reflection_min_group
    groups = list(db.memories.aggregate([
        {"$match": {"workspace_id": ws, "status": "active", "scope": {"$ne": "private"},
                    "type": {"$in": ["outcome", "feedback", "fact", "episode", "decision"]},
                    "topic": {"$ne": "general"}, "flags": {"$nin": ["injection"]}}},
        {"$group": {"_id": "$topic", "ids": {"$push": "$_id"}, "items": {"$push": "$content"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": n}}}, {"$limit": max_groups * 3}]))
    out = []
    for g in groups:
        if len(out) >= max_groups:
            break
        if db.memories.find_one({"workspace_id": ws, "type": "strategy", "status": "active", "derived_from": {"$all": g["ids"]}}):
            continue  # already consolidated
        out.append({"topic": g["_id"], "ids": [str(i) for i in g["ids"]], "items": g["items"], "n": g["n"]})
    return out


def reflect(group: dict) -> dict | None:
    """One LLM call. Returns the raw JSON or None."""
    r = llm.complete_json(prompts.REFLECTION, "Memories:\n" + "\n".join(f"- {i}" for i in group["items"]),
                          settings.llm_model_main, task="reflection", fake={"items": group["items"], "topic": group["topic"]},
                          max_tokens=500)
    return r if isinstance(r, dict) else None


def validate(raw) -> dict | None:
    """Pydantic check. Returns a clean lesson dict or None (the graph then retries)."""
    try:
        return LessonOut(**(raw or {})).model_dump()
    except Exception:
        return None


def save(ws: str, uid: str, group: dict, lesson: dict) -> dict:
    ids = [oid(i) for i in group["ids"]]
    doc = memory.create_memory(ws, uid, {
        "type": "strategy", "topic": group["topic"], "content": lesson["content"], "tags": lesson.get("tags", ["lesson"]),
        "importance": 0.85, "confidence": lesson.get("confidence", 0.65), "derived_from": ids, "agent_id": "reflection-agent",
        "source": {"kind": "reflection", "n": group["n"]}}, actor="reflection-agent", reason=f"consolidated {group['n']} memories")
    memory.lower_importance(ws, group["ids"], 0.8)  # let the lesson rank higher than its sources
    return {"id": str(doc["_id"]), "topic": group["topic"], "content": doc["content"], "from": group["n"]}


def run(ws: str, uid: str = "system", min_group: int | None = None, max_groups: int = 3, **_ignored) -> dict:
    """Plain (no graph) version: used when USE_LANGGRAPH=false."""
    groups = select_groups(ws, min_group, max_groups)
    created = []
    for g in groups:
        for _ in range(2):
            lesson = validate(reflect(g))
            if lesson:
                created.append(save(ws, uid, g, lesson))
                break
    return {"created": created, "groups_checked": len(groups)}
