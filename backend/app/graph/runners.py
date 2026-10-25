"""The ways the rest of the app starts, resumes and observes graph runs (API routes, background tasks, MCP, scheduler)."""
import logging
import time
import uuid

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.core.config import settings
from app.db.mongo import db
from app.graph import threads
from app.graph.registry import freshness_graph, learn_graph, reflection_graph
from app.services import decisions_service as decisions
from app.services import events_service as ev

log = logging.getLogger("teammind.graph")


def workspace_flags(ws: str) -> dict:
    """Per-workspace demo switches (Settings -> Demo mode)."""
    from bson import ObjectId
    try:
        w = db.workspaces.find_one({"_id": ObjectId(ws)}, {"settings": 1}) or {}
    except Exception:
        w = {}
    st = w.get("settings") or {}
    return {"ask_on_conflict": bool(st.get("demo_ask_on_conflict", settings.demo_ask_on_conflict))}


def _cfg(thread_id: str, limit: int | None = None) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": limit or settings.graph_recursion_limit}


def _limit_for(n_candidates: int) -> int:
    """About 8 steps per candidate; a loop over many candidates needs more than the default 25."""
    return max(settings.graph_recursion_limit, 10 * n_candidates + 20)


def _drive(graph, ws: str, uid: str, thread_id: str, payload, cfg: dict) -> dict:
    """Invoke (or resume) a checkpointed graph. If it paused, open a decision for the human (Decision inbox + live event)."""
    try:
        out = graph.invoke(payload, cfg)
    except GraphRecursionError:
        log.warning("graph %s hit the recursion limit", thread_id)
        ev.publish_user(ws, uid, {"kind": "learned", "status": "error", "message": "Stopped: this run took too many steps."})
        threads.set_pending(thread_id, False)
        return {"status": "error", "thread_id": thread_id, "results": [], "error": "recursion limit"}
    asked = out.get("__interrupt__") or []
    pending = []
    for i in asked:
        payload_ = i.value if isinstance(i.value, dict) else {"kind": "conflict", "question": str(i.value)}
        decisions.open_decision(ws, uid, thread_id, payload_, private=bool(payload_.get("private")))
        pending.append(payload_)
    threads.set_pending(thread_id, bool(pending))
    return {"status": "needs_user_choice" if pending else "done", "thread_id": thread_id, "pending": pending,
            "results": out.get("results") or out.get("created") or [], "out": out}


# ---------------------------------------------------------------- Learn graph
def start_learn(ws: str, uid: str, *, user_text: str = "", answer_text: str = "", queue: list | None = None,
                force: dict | None = None, agent_id: str | None = None, actor: str = "agent", notify: bool = True,
                conv_id: str = "run", max_candidates: int | None = None) -> dict:
    """Run the Learn graph to the end, or until it asks a human. Returns {status, thread_id, results, pending}."""
    thread_id = threads.learn_thread(ws, conv_id, uuid.uuid4().hex[:12])
    threads.register(thread_id, ws, uid)
    inputs = {"workspace_id": ws, "user_id": uid, "thread_id": thread_id, "conversation_id": conv_id, "actor": actor,
              "notify": notify, "started_at": time.time(), "max_candidates": max_candidates or settings.learn_max_candidates,
              **workspace_flags(ws)}
    if agent_id:
        inputs["agent_id"] = agent_id
    if force:
        inputs["force"] = force
    elif queue:
        from app.db.schemas import Candidate  # validate + fill defaults once, at the boundary
        inputs["queue"] = [Candidate(**q).model_dump() for q in queue]
    else:
        inputs.update(user_text=user_text, answer_text=answer_text)
    limit = _limit_for(len(queue or []) or inputs["max_candidates"])
    res = _drive(learn_graph, ws, uid, thread_id, inputs, _cfg(thread_id, limit))
    res.pop("out", None)
    return res


def run_chat_learn(ws: str, uid: str, user_text: str, answer_text: str, conv_id: str):
    """Background task after a chat turn: the user never waits for learning."""
    try:
        start_learn(ws, uid, user_text=user_text, answer_text=answer_text, conv_id=conv_id)
    except Exception as e:
        log.exception("learn graph failed")
        ev.log_run("learn", ws, uid, input=user_text, error=str(e))


def resume(ws: str, uid: str, thread_id: str, choice: str) -> dict:
    """Continue a paused run with the human's answer (the graph continues from the node that asked)."""
    graph = reflection_graph if threads.kind_of(thread_id) == "reflect" else learn_graph
    res = _drive(graph, ws, uid, thread_id, Command(resume=choice), _cfg(thread_id, _limit_for(50)))
    res.pop("out", None)
    return res


# ---------------------------------------------------------------- Reflection + Freshness graphs
def run_reflection(ws: str, uid: str = "system", require_approval: bool | None = None) -> dict:
    thread_id = threads.reflect_thread(ws, uuid.uuid4().hex[:12])
    threads.register(thread_id, ws, uid)
    ra = settings.reflection_require_approval if require_approval is None else require_approval
    res = _drive(reflection_graph, ws, uid, thread_id,
                 {"workspace_id": ws, "user_id": uid, "thread_id": thread_id, "require_approval": ra, "created": [], "trace": []},
                 _cfg(thread_id))
    out = res.pop("out", {})
    return {"created": out.get("created") or [], "groups_checked": out.get("groups_checked", 0), "status": res["status"],
            "thread_id": thread_id, "pending": res.get("pending", [])}


def run_freshness(days_ahead: int = 0, ws: str | None = None, dry_run: bool = False) -> dict:
    out = freshness_graph.invoke({"shift_days": days_ahead, "workspace_id": ws, "dry_run": dry_run, "results": []},
                                 {"recursion_limit": 25})
    return out["summary"]
