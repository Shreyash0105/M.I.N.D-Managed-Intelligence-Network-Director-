"""The chat pipeline: Guard -> Planner -> Retriever -> Responder (foreground), then Extractor -> Conflict (background)."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.agents import extractor, guard, planner, responder
from app.agents.conflict import store_candidate
from app.core.config import settings
from app.services import conversations, retrieval_service as retrieval
from app.services import events_service as ev

log = logging.getLogger("teammind.chat")
pool = ThreadPoolExecutor(max_workers=4)


def chat_turn(c, text: str, conversation_id=None, memory_on=True, ephemeral=False):
    """c = Ctx. Yields events for SSE."""
    t0 = time.time()
    g = guard.check(text)
    if g["findings"]:
        yield {"type": "guard", "action": g["action"], "findings": g["findings"]}
    clean = g["clean_text"]

    history, conv_id = [], None
    if not ephemeral:
        conv_id = conversations.ensure(c.ws_id, c.uid, conversation_id, clean)
        yield {"type": "conversation", "id": conv_id}
        history = conversations.last_turns(conv_id, 3)

    plan = planner.plan(clean, history)
    hits, info = [], {"mode": "off", "errors": []}
    if memory_on and plan["need_memory"]:
        hits, info = retrieval.search(plan, c.ws_id, c.uid, k=5)
    items = retrieval.public_view(hits)
    hits = items  # the Responder works on the public, JSON-safe form
    yield {"type": "memories", "items": items, "mode": info["mode"], "plan": plan}

    answer, error = "", None
    try:
        for piece in responder.stream(clean, history, hits):
            answer += piece
            yield {"type": "token", "text": piece}
    except Exception as e:  # LLM down: still be useful
        error = str(e)
        log.exception("Responder failed")
        fb = "The AI model is unavailable right now."
        if hits:
            fb += " Top memories I found:\n" + "\n".join(f"- {h['content']} [m:{h['ref']}]" for h in hits)
        answer += fb
        yield {"type": "token", "text": fb}
        yield {"type": "error", "message": f"LLM error: {e}"[:200]}

    used = responder.parse_used(answer, hits)
    ms = int((time.time() - t0) * 1000)
    if conv_id:
        conversations.append(conv_id, text if not g["findings"] else clean, answer, used,
                             [{"ref": i["ref"], "id": i["id"], "type": i["type"], "topic": i["topic"], "content": i["content"]} for i in items])
    yield {"type": "done", "used_memory_ids": used, "latency_ms": ms, "mode": info["mode"]}
    ev.log_run("chat", c.ws_id, c.uid, input=clean, output=answer, retrieved_ids=[i["id"] for i in items],
               latency_ms=ms, model=settings.llm_model_main, mode=info["mode"],
               error=error or ("; ".join(info["errors"]) or None))

    if memory_on and not ephemeral and c.can_write and g["action"] != "block":
        pool.submit(learn, c.ws_id, c.uid, clean, answer)
    elif g["action"] == "block":
        ev.publish_user(c.ws_id, c.uid, {"kind": "learned", "status": "blocked",
                                         "message": f"I did not save it: it contained a secret ({', '.join(g['findings'])})."})


def learn(ws, uid, user_text, answer_text):
    """Agents 5 + 6 in the background. Each result is pushed to the user as a toast."""
    t0 = time.time()
    try:
        cands = extractor.extract(user_text, answer_text)
        for cand in cands:
            cand.source = {"kind": "chat"}
            r = store_candidate(ws, uid, cand)
            ev.publish_user(ws, uid, {"kind": "learned", **r})
        ev.log_run("learn", ws, uid, input=user_text, output=f"{len(cands)} candidates",
                   latency_ms=(time.time() - t0) * 1000, model=settings.llm_model_fast)
    except Exception as e:
        log.exception("learn failed")
        ev.log_run("learn", ws, uid, input=user_text, error=str(e))
