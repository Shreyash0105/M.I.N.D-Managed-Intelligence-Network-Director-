"""TeamMind MCP server. Run:  TEAMMIND_TOKEN=tm_xxx python mcp_server/server.py   (stdio)
Outside agents (Claude Code, Cursor, Codex) call these tools; TeamMind runs Guard, Conflict Resolver, Retriever for them."""
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # so .env is found

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.agents.conflict import store_candidate  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.util import utcnow  # noqa: E402
from app.db.mongo import db  # noqa: E402
from app.db.schemas import Candidate  # noqa: E402
from app.services import memory_service as memory, retrieval_service as retrieval  # noqa: E402

mcp = FastMCP("teammind-memory")


def _auth(write=False):
    tok = os.getenv("TEAMMIND_TOKEN")
    if not tok:
        raise RuntimeError("TEAMMIND_TOKEN is not set")
    t = db.api_tokens.find_one({"token_hash": hashlib.sha256(tok.encode()).hexdigest()})
    if not t:
        raise RuntimeError("Invalid TEAMMIND_TOKEN")
    if write and t.get("scope") != "readwrite":
        raise RuntimeError("This agent token is read-only")
    db.api_tokens.update_one({"_id": t["_id"]}, {"$set": {"last_used_at": utcnow()}})
    return t["workspace_id"], t["user_id"], f"agent:{t['label']}"


def _words(q):
    return [w for w in q.replace("?", " ").split() if len(w) > 3][:6]


def _answer(run: dict) -> dict:
    """The Learn graph either finished or paused to ask a human (Decision inbox in the web app)."""
    if run["status"] == "needs_user_choice":
        return {"status": "needs_user_choice", "thread_id": run["thread_id"],
                "tell_the_human": "TeamMind is unsure how this fits with an older memory. Ask them to open TeamMind > Decisions."}
    return run["results"][-1] if run["results"] else {"status": "none", "message": "Nothing was saved."}


@mcp.tool()
def recall(query: str, k: int = 5, types: list[str] | None = None) -> list[dict]:
    """Ask what the team already decided or remembers about a topic. Call this BEFORE writing code or
    making a design choice, so you follow existing decisions and constraints."""
    ws, uid, _ = _auth()
    plan = {"search_query": query, "keywords": _words(query), "types": types or [], "need_memory": True}
    if settings.use_langgraph:  # the same Retrieve subgraph the Chat graph uses (a ready plan skips the Planner)
        from app.graph.chat_graph import retrieve_graph
        out = retrieve_graph.invoke({"workspace_id": ws, "user_id": uid, "plan": plan, "k": k, "types_filter": types or [],
                                     "trace": []})
        items = out.get("hits") or []
    else:
        hits, _info = retrieval.search(plan, ws, uid, k=k, types_filter=types or None)
        items = retrieval.public_view(hits)
    return [{k_: v[k_] for k_ in ("id", "type", "topic", "content", "status", "confidence", "why")} for v in items]


@mcp.tool()
def remember(content: str, type: str = "decision", tags: list[str] | None = None, scope: str = "workspace",
             topic: str = "general") -> dict:
    """Save a decision, constraint, preference, feedback or outcome for the whole team.
    Contradictions with older memories are resolved automatically (old one is kept as history)."""
    ws, uid, agent = _auth(write=True)
    cand = Candidate(content=content, type=type, tags=tags or [], scope=scope, topic=topic,
                     agent_id=agent, source={"kind": "mcp", "agent": agent})
    if not settings.use_langgraph:
        return store_candidate(ws, uid, cand, actor=agent)
    from app.graph import runners
    return _answer(runners.start_learn(ws, uid, queue=[cand.model_dump()], agent_id=agent, actor=agent, notify=False,
                                       conv_id="mcp"))


@mcp.tool()
def correct(memory_id: str, new_content: str, reason: str = "agent correction") -> dict:
    """Fix a wrong or outdated memory. Creates a new version and marks the old one superseded."""
    ws, uid, agent = _auth(write=True)
    if not settings.use_langgraph:
        new = memory.correct(ws, uid, memory_id, new_content, reason, actor=agent)
        return {"status": "superseded", "id": str(new["_id"])}
    from app.graph import runners
    run = runners.start_learn(ws, uid, force={"target_id": memory_id, "content": new_content, "reason": reason},
                              agent_id=agent, actor=agent, notify=False, conv_id="mcp")
    r = run["results"][-1] if run["results"] else {"status": "none"}
    return {"status": r["status"], "id": r.get("id"), "message": r.get("message")}


@mcp.tool()
def forget(memory_id: str, reason: str = "agent request") -> dict:
    """Soft-delete a memory (it can be restored in the web app)."""
    ws, uid, agent = _auth(write=True)
    memory.soft_delete(ws, uid, memory_id, actor=agent, reason=reason)
    return {"status": "deleted", "id": memory_id}


@mcp.tool()
def list_decisions(topic: str = "") -> list[dict]:
    """List the team's current (active) decisions and constraints, optionally filtered by a word."""
    ws, uid, _ = _auth()
    out = []
    for t in ("decision", "constraint"):
        out += memory.list_memories(ws, uid, type=t, status="active", q=topic or None, page_size=30)["items"]
    return [{k: m[k] for k in ("id", "type", "topic", "content")} for m in out]


@mcp.tool()
def open_questions() -> list[dict]:
    """Show unresolved items: facts tagged 'question'."""
    ws, uid, _ = _auth()
    items = memory.list_memories(ws, uid, type="fact", status="active", tag="question", page_size=30)["items"]
    return [{k: m[k] for k in ("id", "topic", "content")} for m in items]


if __name__ == "__main__":
    mcp.run()  # stdio transport
