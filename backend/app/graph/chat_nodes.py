"""Chat graph nodes: thin wrappers around the plain functions in agents/ and services/ (those have their own tests)."""
import time

from langchain_core.messages import AIMessage, HumanMessage

from app.agents import guard, planner, responder
from app.core.config import settings
from app.graph.state import RESET
from app.graph.tracing import traced, writer
from app.services import conversations, retrieval_service as retrieval
from app.services import events_service as ev


def _history(s: dict, n: int = 6) -> list[dict]:
    """Earlier turns (everything before the newest user message) as plain {role, text} dicts."""
    out = []
    for m in (s.get("messages") or [])[:-1][-n:]:
        out.append({"role": "user" if m.type == "human" else "assistant", "text": str(m.content)})
    return out


# ---------------------------------------------------------------- Agent 1: guard
@traced("guard")
def guard_node(s):
    """Cleans the text, decides allow / save_private / block, and RESETS the per-turn fields:
    a thread remembers old values between turns, so last turn's answer must not leak into this one."""
    g = guard.check(s["user_text"])
    if g["findings"]:
        writer()({"type": "guard", "action": g["action"], "findings": g["findings"]})
    msgs = [HumanMessage(content=g["clean_text"])]
    if not s.get("messages") and s.get("conversation_id"):
        # first turn of this thread but the conversation already has history (older chat, purged thread): seed from the DB
        seed = [(HumanMessage if t["role"] == "user" else AIMessage)(content=t["text"])
                for t in conversations.last_turns(s["conversation_id"], 3)]
        msgs = seed + msgs
    return {"guard": g, "clean_text": g["clean_text"], "plan": {}, "hits": [], "retrieval_mode": "", "answer": "",
            "used_memory_ids": [], "llm_error": "", "memory_only": False, "started_at": time.time(),
            "messages": msgs, "trace": [RESET, {"node": "guard", "action": g["action"], "findings": g["findings"]}]}


def after_guard(s):
    if s["guard"]["action"] == "block":
        return "blocked"
    return "retrieve" if s.get("memory_on", True) else "respond"


@traced("blocked_reply")
def blocked_node(s):
    """A secret was found: nothing goes to the LLM or the database."""
    what = ", ".join(s["guard"]["findings"]) or "a secret"
    text = f"I did not save or process that message because it contained a secret ({what}). Remove it and send it again."
    writer()({"type": "memories", "items": [], "mode": "off", "plan": {}})
    writer()({"type": "token", "text": text})
    ev.publish_user(s["workspace_id"], s["user_id"], {"kind": "learned", "status": "blocked",
                                                       "message": f"I did not save it: it contained a secret ({what})."})
    return {"answer": text, "messages": [AIMessage(content=text)]}


# ---------------------------------------------------------------- Agents 2 + 3: the Retrieve subgraph
@traced("planner", model=settings.llm_model_fast)
def planner_node(s):
    plan = planner.plan(s["clean_text"], s.get("history") or [])
    return {"plan": plan, "trace": [{"node": "planner", "need_memory": plan["need_memory"]}]}


@traced("retriever")
def retriever_node(s):
    hits, info = retrieval.search(s["plan"], s["workspace_id"], s["user_id"], k=s.get("k") or 5,
                                  track=s.get("track", True), types_filter=s.get("types_filter") or None)
    items = retrieval.public_view(hits)
    writer()({"type": "memories", "items": items, "mode": info["mode"], "plan": s["plan"]})  # chips appear NOW
    return {"hits": items, "retrieval_mode": info["mode"],
            "trace": [{"node": "retriever", "n": len(items), "mode": info["mode"], "errors": info["errors"][:2]}]}


def retrieve_node(s):
    """The Chat graph's 'retrieve' step: runs the reusable Retrieve subgraph and forwards its live events.
    (A compiled subgraph added directly as a node would duplicate reducer lists and hide custom events,
    so this thin wrapper hands it only what it needs and takes back only what it produced.)"""
    from app.graph.chat_graph import retrieve_graph
    w = writer()
    sub_in = {"workspace_id": s["workspace_id"], "user_id": s["user_id"], "clean_text": s["clean_text"],
              "history": _history(s), "k": s.get("k") or 5, "track": s.get("track", True),
              "types_filter": s.get("types_filter") or [], "trace": []}
    last = {}
    for mode, chunk in retrieve_graph.stream(sub_in, {"recursion_limit": 25}, stream_mode=["custom", "values"]):
        if mode == "custom":
            w(chunk)
        else:
            last = chunk
    return {"plan": last.get("plan") or {}, "hits": last.get("hits") or [], "retrieval_mode": last.get("retrieval_mode") or "",
            "trace": last.get("trace") or []}


# ---------------------------------------------------------------- Agent 4: responder
@traced("responder", model=settings.llm_model_main)
def responder_node(s):
    w = writer()
    hits = s.get("hits") or []
    if not s.get("retrieval_mode"):  # memory off, or small talk: tell the UI there are no chips
        w({"type": "memories", "items": [], "mode": "off", "plan": s.get("plan") or {}})
    answer, err = "", ""
    try:
        for piece in responder.stream(s["clean_text"], _history(s), hits):  # tokens are streamed as they arrive
            answer += piece
            w({"type": "token", "text": piece})
    except Exception as e:  # LLM down (the provider already retried once): still be useful
        err = str(e)[:200]
        fb = "The AI model is unavailable right now (memory only mode)."
        if hits:
            fb += " Top memories I found:\n" + "\n".join(f"- {h['content']} [m:{h['ref']}]" for h in hits)
        answer += fb
        w({"type": "token", "text": fb})
        w({"type": "error", "message": f"LLM error: {err}"})
    used = responder.parse_used(answer, hits)
    return {"answer": answer, "used_memory_ids": used, "llm_error": err, "memory_only": bool(err),
            "messages": [AIMessage(content=answer)], "trace": [{"node": "responder", "used": used, "error": err or None}]}


# ---------------------------------------------------------------- finalize
def finalize_node(s):
    """Saves the conversation and the audit row, then strips memory text from the state (ids only)
    so the final checkpoint of the thread holds no copy of the team's knowledge."""
    t = time.time()
    hits = s.get("hits") or []
    conv = s.get("conversation_id")
    if conv:
        conversations.append(conv, s["clean_text"], s.get("answer", ""), s.get("used_memory_ids", []),
                             [{"ref": h["ref"], "id": h["id"], "type": h["type"], "topic": h["topic"], "content": h["content"]}
                              for h in hits])
    save_ms = int((time.time() - t) * 1000)
    trace = list(s.get("trace") or []) + [{"node": "finalize", "ms": save_ms}]
    started = s.get("started_at") or time.time()
    ev.log_run("chat", s["workspace_id"], s["user_id"], input=s["clean_text"], output=s.get("answer", ""),
               retrieved_ids=[h["id"] for h in hits], latency_ms=(time.time() - started) * 1000,
               model=settings.llm_model_main, mode=s.get("retrieval_mode") or "off",
               error=s.get("llm_error") or None, conversation_id=conv or None, trace=trace)
    return {"hits": [{"id": h["id"], "ref": h["ref"]} for h in hits], "trace": [{"node": "finalize", "ms": save_ms}]}
