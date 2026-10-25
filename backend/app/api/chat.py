import json
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agents import guard
from app.agents.orchestrator import chat_turn
from app.core.config import settings
from app.core.security import ctx, rate_limit
from app.core.util import public
from app.db.mongo import db
from app.db.schemas import ChatIn
from app.services import conversations

router = APIRouter()
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(e) -> str:
    return f"data: {json.dumps(public(e), default=str)}\n\n"


@router.post("/chat")
def chat(body: ChatIn, bg: BackgroundTasks, c=Depends(ctx)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Say something first")
    rate_limit(c.uid)
    if not settings.use_langgraph:  # fallback: the plain-function pipeline of version 1.0
        def old():
            try:
                for e in chat_turn(c, text, body.conversation_id, body.memory_on, body.ephemeral):
                    yield _sse(e)
            except Exception as ex:
                yield _sse({"type": "error", "message": str(ex)[:200]})
        return StreamingResponse(old(), media_type="text/event-stream", headers=HEADERS)

    from app.graph import threads
    from app.graph.registry import chat_graph
    from app.graph.runners import run_chat_learn

    def gen():
        t0 = time.time()
        try:
            conv_id = None
            if not body.ephemeral:  # Compare runs leave no conversation behind
                conv_id = conversations.ensure(c.ws_id, c.uid, body.conversation_id, guard.check(text)["clean_text"])
                yield _sse({"type": "conversation", "id": conv_id})
            thread = threads.chat_thread(c.ws_id, conv_id or f"eph-{uuid.uuid4().hex[:10]}")  # tenant check = prefix check
            threads.register(thread, c.ws_id, c.uid, ephemeral=conv_id is None)
            cfg = {"configurable": {"thread_id": thread}, "recursion_limit": settings.graph_recursion_limit}
            inputs = {"workspace_id": c.ws_id, "user_id": c.uid, "conversation_id": conv_id or "", "user_text": text,
                      "memory_on": body.memory_on, "k": 5}
            for chunk in chat_graph.stream(inputs, cfg, stream_mode="custom"):  # memory chips, guard banners, answer tokens
                yield _sse(chunk)
            final = chat_graph.get_state(cfg).values
            yield _sse({"type": "done", "used_memory_ids": final.get("used_memory_ids", []), "mode": final.get("retrieval_mode") or "off",
                        "latency_ms": int((time.time() - t0) * 1000), "memory_only": bool(final.get("memory_only"))})
            if body.memory_on and conv_id and c.can_write and final["guard"]["action"] != "block":
                bg.add_task(run_chat_learn, c.ws_id, c.uid, final["clean_text"], final.get("answer", ""), conv_id)  # after the stream ends
        except Exception as ex:
            yield _sse({"type": "error", "message": str(ex)[:200]})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=HEADERS)


@router.get("/conversations")
def list_conversations(c=Depends(ctx)):
    return {"items": conversations.list_for(c.ws_id, c.uid)}


@router.get("/conversations/{cid}")
def get_conversation(cid: str, c=Depends(ctx)):
    conv = conversations.get(c.ws_id, c.uid, cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/runs/{conversation_id}")
def runs(conversation_id: str, c=Depends(ctx)):
    """Node-by-node trace (nodes, milliseconds, models) of the latest chat turns of one of the user's conversations."""
    if not conversations.get(c.ws_id, c.uid, conversation_id):
        raise HTTPException(404, "Conversation not found")
    cur = db.agent_runs.find({"workspace_id": c.ws_id, "user_id": c.uid, "conversation_id": conversation_id, "name": "chat"}) \
        .sort("ts", -1).limit(10)
    return {"items": [public({**r, "id": r.pop("_id")}) for r in cur]}
