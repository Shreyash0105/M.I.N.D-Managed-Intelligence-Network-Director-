import uuid

from app.db.mongo import db
from app.graph.registry import chat_graph


def run_chat(ws, text, conv=None, memory_on=True, uid=None):
    conv = conv or uuid.uuid4().hex[:12]
    cfg = {"configurable": {"thread_id": f"chat:{ws['id']}:{conv}"}}
    events = list(chat_graph.stream({"workspace_id": ws["id"], "user_id": uid or ws["alex"], "conversation_id": "",
                                     "user_text": text, "memory_on": memory_on, "k": 5}, cfg, stream_mode="custom"))
    return events, chat_graph.get_state(cfg).values, cfg


def test_memory_changes_the_answer_and_cites_the_memory(ws, mem):
    m = mem("We cannot use paid APIs. Free tiers and local embeddings only.", type="constraint", topic="budget",
            tags=["budget", "tools", "free"])
    ev_on, st_on, _ = run_chat(ws, "Which tools should we use for the demo? Any paid APIs?", memory_on=True)
    assert any(e["type"] == "memories" and e["items"] for e in ev_on)           # memory chips streamed
    assert "".join(e["text"] for e in ev_on if e["type"] == "token")           # answer tokens streamed
    assert str(m["_id"]) in st_on["used_memory_ids"]                           # cites the memory id
    ev_off, st_off, _ = run_chat(ws, "Which tools should we use for the demo? Any paid APIs?", memory_on=False)
    assert st_off["used_memory_ids"] == [] and "[m:" not in st_off["answer"]   # behaviour differs without memory
    assert "retriever" not in [t["node"] for t in st_off["trace"]]             # retrieve was skipped


def test_trace_has_nodes_and_resets_every_turn(ws, mem):
    mem("Demo day is on Saturday at 3 pm.", type="fact", topic="schedule", tags=["demo"])
    _, st1, cfg = run_chat(ws, "When is demo day?", conv="same")
    nodes1 = [t["node"] for t in st1["trace"]]
    assert nodes1[0] == "guard" and nodes1[-1] == "finalize" and "responder" in nodes1
    assert all("ms" in t for t in st1["trace"])
    _, st2, _ = run_chat(ws, "When is demo day again?", conv="same")           # same thread, second turn
    assert [t["node"] for t in st2["trace"]].count("guard") == 1                # per-turn fields were reset
    assert len(st2["messages"]) == 4                                            # messages reducer appended, not replaced


def test_secret_is_blocked_before_llm_and_database(ws):
    events, st, _ = run_chat(ws, "deploy with key sk-TESTTESTTESTTESTTESTTEST please")
    assert any(e["type"] == "guard" and e["action"] == "block" for e in events)
    assert st["guard"]["action"] == "block"
    assert "retriever" not in [t["node"] for t in st["trace"]] and "responder" not in [t["node"] for t in st["trace"]]
    assert "sk-TEST" not in str(st["messages"]) and "sk-TEST" not in st["answer"]


def test_checkpoint_is_json_safe_without_vectors_or_memory_text(ws, mem):
    mem("We use FastAPI with MongoDB Atlas.", type="decision", topic="tech stack", tags=["stack"])
    _, st, cfg = run_chat(ws, "What is our tech stack?")
    assert all(set(h) == {"id", "ref"} for h in st["hits"])                    # finalize stripped the memory text
    raw = db.checkpoints.find_one({"thread_id": cfg["configurable"]["thread_id"]})
    assert raw is not None                                                      # state really lives in MongoDB
    assert "embedding" not in str(st)


def test_llm_down_falls_back_to_memory_only(ws, mem, monkeypatch):
    mem("We use FastAPI with MongoDB Atlas.", type="decision", topic="tech stack", tags=["stack", "fastapi"])
    from app.llm import provider

    def boom(*a, **k):
        raise RuntimeError("model down")
        yield  # pragma: no cover
    monkeypatch.setattr(provider, "stream", boom)
    events, st, _ = run_chat(ws, "What is our tech stack with FastAPI?")
    assert st["memory_only"] is True and "memory only mode" in st["answer"]
    assert any(e["type"] == "error" for e in events)
