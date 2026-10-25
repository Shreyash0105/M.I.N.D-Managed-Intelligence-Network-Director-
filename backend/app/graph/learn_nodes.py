"""Learn graph nodes (Agents 5 + 6 + Guard on candidates). Thin wrappers over agents/ and the memory service.

Outcome nodes (save_new, reinforce, supersede, force_supersede) are the ONLY writers to the memories collection,
and all of them go through services/memory_service.py (supersede uses a transaction)."""
import logging
import time
from typing import Literal

from fastapi import HTTPException
from langgraph.types import Command, interrupt

from app.agents import conflict, extractor, guard
from app.core.config import settings
from app.db.schemas import Candidate
from app.graph import threads
from app.graph.tracing import traced
from app.services import events_service as ev
from app.services import memory_service as memory, retrieval_service as retrieval
from app.services.embeddings import embed, memory_text

log = logging.getLogger("teammind.learn")


def _actor(s) -> str:
    return s.get("actor") or "agent"


def _brief(d: dict) -> dict:
    return {"id": d["id"], "type": d.get("type"), "topic": d.get("topic"), "content": d.get("content")}


def _data(s) -> dict:
    d = dict(s["current"])
    a = _actor(s)
    d["agent_id"] = d.get("agent_id") or s.get("agent_id") or (a if a.startswith("agent:") else None)
    return d


def _note(s) -> str:
    f = (s.get("guard") or {}).get("findings") or []
    return f" (hid {', '.join(f)})" if f else ""


def _made(doc: dict, status: str, msg: str, note: str = "", old_id=None) -> dict:
    r = {"status": status, "id": str(doc["_id"]), "message": msg + note,
         "memory": {"id": str(doc["_id"]), "type": doc["type"], "topic": doc.get("topic"), "content": doc["content"]}}
    if old_id:
        r["old_id"] = str(old_id)
    if "injection" in doc.get("flags", []):
        r.update(status="saved_flagged", message="Saved but flagged as a possible prompt injection; it will never be shown to the AI.")
    return r


# ---------------------------------------------------------------- nodes
@traced("extractor", model=settings.llm_model_fast)
def extractor_node(s):
    cands = extractor.extract(s["user_text"], s.get("answer_text", ""))  # Agent 5 (plain function)
    cap = s.get("max_candidates") or settings.learn_max_candidates
    queue = [{**c.model_dump(), "source": {"kind": "chat"}} for c in cands[:cap]]
    return {"queue": queue, "truncated": max(0, len(cands) - cap), "trace": [{"node": "extractor", "n": len(cands)}]}


@traced("pick_next")
def pick_next(s):
    """Take ONE candidate from the queue. One at a time keeps pause/resume simple and safe."""
    q = s["queue"]
    return {"current": q[0], "queue": q[1:], "guard": {}, "similar": [], "verdict": {}}


@traced("guard_candidate")
def guard_candidate(s):
    """Agent 1 again, now on a memory candidate: secrets are never saved, personal data makes it private."""
    g = guard.check(s["current"]["content"])
    cur = {**s["current"], "content": g["clean_text"]}
    if g["action"] == "save_private":
        cur["scope"] = "private"
    return {"guard": g, "current": cur, "trace": [{"node": "guard_candidate", "action": g["action"]}]}


@traced("find_similar")
def find_similar(s):
    data = s["current"]
    sims = retrieval.similar(embed(memory_text(data)), s["workspace_id"], s["user_id"], limit=5)
    brief = [{"id": str(d["_id"]), "type": d["type"], "topic": d.get("topic"), "content": d["content"],
              "scope": d.get("scope"), "sem": round(d["_sem"], 3)} for d in sims]
    return {"similar": brief, "trace": [{"node": "find_similar", "n": len(brief)}]}


@traced("judge", model=settings.llm_model_fast)
def judge_node(s):
    """Agent 6 (LLM): duplicate | refines | contradicts | unrelated."""
    sims = s["similar"]
    v = conflict.judge(Candidate(**s["current"]), sims)
    target = sims[v.target - 1] if v.target and 1 <= v.target <= len(sims) else None
    relation = v.relation if target else "unrelated"
    conf = v.confidence
    if s.get("ask_on_conflict") and relation == "contradicts":  # demo mode: always ask a human about contradictions
        conf = min(conf, settings.judge_confidence_min - 0.1)
    verdict = {"relation": relation, "confidence": round(conf, 3), "reason": v.reason, "merged_content": v.merged_content,
               "target_id": target["id"] if target else None, "target_content": target["content"] if target else None,
               "target_scope": target.get("scope") if target else None}
    return {"verdict": verdict, "trace": [{"node": "judge", "relation": relation, "confidence": verdict["confidence"]}]}


@traced("save_new")
def save_new_node(s):
    try:
        data = _data(s)
        doc = memory.create_memory(s["workspace_id"], s["user_id"], data, _actor(s))
        return {"results": [_made(doc, "saved", f"Remembered: {data['type']} - {data['topic']}", _note(s))]}
    except Exception as e:
        log.exception("save_new failed")
        return {"results": [{"status": "error", "message": f"Could not save: {str(e)[:120]}"}]}


@traced("reinforce")
def reinforce_node(s):
    v = s["verdict"]
    try:
        memory.reinforce(s["workspace_id"], v["target_id"])
        old = next((x for x in s["similar"] if x["id"] == v["target_id"]), {"id": v["target_id"]})
        return {"results": [{"status": "reinforced", "id": v["target_id"], "memory": _brief(old),
                             "message": "Already known. Reinforced the existing memory."}]}
    except Exception as e:
        log.exception("reinforce failed")
        return {"results": [{"status": "error", "message": f"Could not reinforce: {str(e)[:120]}"}]}


@traced("supersede")
def supersede_node(s):
    v = s["verdict"]
    data = _data(s)
    if v["relation"] == "refines" and v.get("merged_content"):
        data["content"] = v["merged_content"]
    ws, uid = s["workspace_id"], s["user_id"]
    try:
        new = memory.supersede(ws, uid, v["target_id"], data, _actor(s), v.get("reason") or v["relation"])  # transaction
        return {"results": [_made(new, "superseded", f"You said \"{(v.get('target_content') or '')[:60]}\" before; now updated.",
                                  _note(s), old_id=v["target_id"])]}
    except HTTPException:  # the old memory vanished while we waited for the human: just save the new one
        doc = memory.create_memory(ws, uid, data, _actor(s))
        return {"results": [_made(doc, "saved", f"Remembered: {data['type']} - {data['topic']}", _note(s))]}
    except Exception as e:
        log.exception("supersede failed")
        return {"results": [{"status": "error", "message": f"Could not update: {str(e)[:120]}"}]}


@traced("force_supersede")
def force_supersede_node(s):
    """MCP `correct` and PATCH /memories/{id}: no judge needed, the caller already knows which memory is wrong."""
    f = s["force"]
    try:
        new = memory.correct(s["workspace_id"], s["user_id"], f["target_id"], f["content"], f.get("reason") or "manual correction",
                             actor=_actor(s))
        return {"results": [_made(new, "superseded", "Corrected. Old version kept as superseded.", old_id=f["target_id"])]}
    except HTTPException as e:
        return {"results": [{"status": "error", "message": str(e.detail)}]}


@traced("skip")
def skip_node(s):
    f = (s.get("guard") or {}).get("findings") or []
    return {"results": [{"status": "blocked", "findings": f, "message": f"Not saved: it looks like a secret ({', '.join(f)})."}]}


@traced("ask_user")
def ask_user(s) -> Command[Literal["supersede", "record_result", "save_new"]]:
    """The judge is unsure: PAUSE the whole run until a human decides. State is saved in MongoDB under the thread_id."""
    v = s["verdict"]
    cur = s["current"]
    choice = interrupt({"kind": "conflict", "question": "Which statement is correct?",   # <- the graph stops here
                        "new": cur["content"], "old": v.get("target_content"), "target_id": v.get("target_id"),
                        "relation": v["relation"], "confidence": v["confidence"], "reason": v.get("reason"),
                        "private": cur.get("scope") == "private" or v.get("target_scope") == "private"})
    # --- on resume this node runs again from the top, so everything above must be free of side effects ---
    goto = {"use_new": "supersede", "keep_old": "record_result", "keep_both": "save_new"}[choice]
    if choice == "keep_old":
        return Command(update={"results": [{"status": "kept_old", "id": v.get("target_id"),
                                            "message": "Kept the old memory; the new statement was not saved."}]}, goto=goto)
    return Command(update={}, goto=goto)


@traced("record_result")
def record_result(s):
    """One toast / banner per candidate (chat runs). API and MCP runs return their results instead."""
    r = s["results"][-1] if s.get("results") else {"status": "none", "message": ""}
    if s.get("notify"):
        ev.publish_user(s["workspace_id"], s["user_id"], {"kind": "learned", **r})
    return {"trace": [{"node": "record_result", "status": r.get("status")}]}


@traced("publish_summary")
def publish_summary(s):
    res = s.get("results") or []
    if s.get("truncated") and s.get("notify"):
        ev.publish_user(s["workspace_id"], s["user_id"], {"kind": "learned", "status": "capped",
                                                           "message": f"Stopped after {len(res)} memories ({s['truncated']} more were skipped)."})
    if s.get("thread_id"):
        threads.set_pending(s["thread_id"], False)
    started = s.get("started_at") or time.time()
    ev.log_run("learn", s["workspace_id"], s["user_id"], input=s.get("user_text") or (s.get("force") or {}).get("content", ""),
               output=f"{len(res)} results: " + ", ".join(r.get("status", "?") for r in res)[:300],
               latency_ms=(time.time() - started) * 1000, model=settings.llm_model_fast,
               thread_id=s.get("thread_id"), trace=list(s.get("trace") or []))
    return {"trace": [{"node": "publish_summary", "n": len(res)}]}


# ---------------------------------------------------------------- routers: tiny pure functions that return the next node
def entry(s):
    if s.get("force"):
        return "force_supersede"
    return "pick_next" if s.get("queue") else "extractor"


def after_extract(s):
    return "pick_next" if s.get("queue") else "end"


def after_guard(s):
    return "skip" if s["guard"]["action"] == "block" else "find_similar"


def after_find(s):
    return "judge" if s.get("similar") else "save_new"


def after_judge(s):
    v = s["verdict"]
    if v["relation"] == "unrelated" or not v.get("target_id"):
        return "save_new"
    if v["confidence"] < settings.judge_confidence_min:
        return "ask_user"  # unsure -> a human decides
    return {"duplicate": "reinforce", "refines": "supersede", "contradicts": "supersede"}.get(v["relation"], "save_new")


def after_record(s):
    return "pick_next" if s.get("queue") else "publish_summary"
