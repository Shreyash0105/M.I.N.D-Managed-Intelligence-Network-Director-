import json
import time

import pytest
from fastapi.testclient import TestClient

from app.db.mongo import db
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs the lifespan: graphs, change streams, scheduler
        yield c


def login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(client, email, ws):
    return {"Authorization": f"Bearer {login(client, email)}", "X-Workspace": ws["id"]}


def sse(resp):
    return [json.loads(p[6:]) for p in resp.text.split("\n\n") if p.startswith("data: ")]


def wait_for(fn, timeout=8):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return None


def chat(client, h, text, **kw):
    r = client.post("/chat", headers=h, json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return sse(r)


def test_chat_streams_events_in_order_and_learns_in_background(client, ws):
    h = H(client, "alex@demo.com", ws)
    ev = chat(client, h, "Remember: we cannot use paid APIs.")
    types = [e["type"] for e in ev]
    assert types[0] == "conversation" and "memories" in types and "token" in types and types[-1] == "done"
    assert ev[-1]["mode"] in ("off", "none", "local-fallback", "hybrid", "vector-only", "keyword-only")
    mem = wait_for(lambda: db.memories.find_one({"workspace_id": ws["id"], "type": "constraint"}))
    assert mem, "the Learn graph (background task) should have saved the constraint"
    # new conversation: the answer cites the memory, and Compare (ephemeral, memory off) does not
    ev2 = chat(client, h, "Which tools should we use? Any paid APIs?")
    done = ev2[-1]
    assert str(mem["_id"]) in done["used_memory_ids"]
    time.sleep(1.5)  # let the background Learn run of the previous turn finish
    before = db.memories.count_documents({"workspace_id": ws["id"]})
    off = chat(client, h, "Which tools should we use? Any paid APIs?", memory_on=False, ephemeral=True)
    assert off[-1]["used_memory_ids"] == [] and not any(e["type"] == "conversation" for e in off)
    time.sleep(1.5)
    assert db.memories.count_documents({"workspace_id": ws["id"]}) == before     # compare did not learn


def test_blocked_secret_shows_banner_and_saves_nothing(client, ws):
    h = H(client, "alex@demo.com", ws)
    ev = chat(client, h, "my key is sk-TESTTESTTESTTESTTESTTEST remember it")
    assert any(e["type"] == "guard" and e["action"] == "block" for e in ev)
    time.sleep(1)
    assert db.memories.count_documents({"workspace_id": ws["id"]}) == 0
    assert "sk-TEST" not in json.dumps(list(db.conversations.find({"workspace_id": ws["id"]}, {"_id": 0})), default=str)


def test_run_trace_endpoint(client, ws):
    h = H(client, "alex@demo.com", ws)
    cid = chat(client, h, "hello team")[0]["id"]
    r = client.get(f"/runs/{cid}", headers=h)
    assert r.status_code == 200
    nodes = [t["node"] for t in r.json()["items"][0]["trace"]]
    assert nodes[0] == "guard" and "finalize" in nodes
    other = H(client, "priya@demo.com", ws)                                       # another user's conversation
    assert client.get(f"/runs/{cid}", headers=other).status_code == 404


def test_decision_inbox_pause_resume_and_tenant_check(client, ws, mem):
    old = mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    alex, priya = H(client, "alex@demo.com", ws), H(client, "priya@demo.com", ws)
    chat(client, alex, "Maybe we switched to GraphQL for all endpoints.")
    row = wait_for(lambda: db.memory_events.find_one({"workspace_id": ws["id"], "action": "needs_user_choice", "resolved": False}))
    assert row, "unsure judge should have paused the Learn graph and opened a decision"
    pend = client.get("/decisions/pending", headers=priya).json()["items"]        # teammate sees workspace decisions
    assert len(pend) == 1 and pend[0]["payload"]["kind"] == "conflict"
    tid = pend[0]["thread_id"]
    # tenant check: a user of ANOTHER workspace cannot touch the thread
    reg = client.post("/auth/register", json={"name": "Eve", "email": f"eve{time.time_ns()}@x.com", "password": "secret1"}).json()
    eve = {"Authorization": f"Bearer {reg['token']}", "X-Workspace": reg["workspaces"][0]["id"]}
    assert client.post(f"/decisions/{tid}/resume", headers=eve, json={"choice": "use_new"}).status_code == 403
    assert client.post(f"/decisions/{tid}/resume", headers=priya, json={"choice": "nonsense"}).status_code == 422
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "active"        # graph not touched by failed attempts
    r = client.post(f"/decisions/{tid}/resume", headers=priya, json={"choice": "use_new"})
    assert r.status_code == 200 and r.json()["results"][-1]["status"] == "superseded"
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "superseded"
    assert client.post(f"/decisions/{tid}/resume", headers=priya, json={"choice": "use_new"}).status_code == 404   # no double resume
    assert client.get("/decisions/pending", headers=alex).json()["items"] == []


def test_viewer_cannot_resume(client, ws, mem):
    mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    db.workspaces.update_one({"_id": __import__("bson").ObjectId(ws["id"])}, {"$set": {"members.1.role": "viewer"}})
    alex, priya = H(client, "alex@demo.com", ws), H(client, "priya@demo.com", ws)
    chat(client, alex, "Maybe we switched to GraphQL for all endpoints.")
    row = wait_for(lambda: db.memory_events.find_one({"workspace_id": ws["id"], "action": "needs_user_choice", "resolved": False}))
    assert client.post(f"/decisions/{row['thread_id']}/resume", headers=priya, json={"choice": "use_new"}).status_code == 403


def test_rest_create_patch_import_and_consolidate_go_through_graphs(client, ws, mem):
    h = H(client, "alex@demo.com", ws)
    r = client.post("/memories", headers=h, json={"content": "We deploy on Thursdays only.", "type": "decision"}).json()
    assert r["status"] == "saved" and r["id"]
    p = client.patch(f"/memories/{r['id']}", headers=h, json={"content": "We deploy on Wednesdays only.", "reason": "fix"})
    assert p.status_code == 200 and p.json()["status"] == "superseded"
    assert db.memories.find_one({"_id": __import__("bson").ObjectId(r["id"])})["status"] == "superseded"
    bad = client.patch(f"/memories/{r['id']}", headers=h, json={"content": "password: hunter2hunter2"})
    assert bad.status_code == 400
    c = client.post("/memories/import/commit", headers=h, json={"items": [
        {"content": "The client cannot use Google services.", "type": "constraint", "topic": "client"},
        {"content": "Priya prefers short stand-ups.", "type": "preference", "topic": "meetings"}]}).json()
    assert [x["status"] for x in c["results"]] == ["saved", "saved"]
    for t in ("deploy failed one", "deploy failed two", "deploy failed three"):
        mem(t, type="outcome", topic="deploys")
    cons = client.post("/memories/consolidate", headers=h, json={}).json()
    assert len(cons["created"]) == 1 and cons["status"] == "done"


def test_admin_endpoints(client, ws):
    h = H(client, "alex@demo.com", ws)
    health = client.get("/admin/health", headers=h).json()
    assert health["graphs"]["checkpointer"] == "mongodb" and set(health["graphs"]["compiled"]) >= {"chat", "learn", "reflection", "freshness"}
    g = client.get("/admin/graphs", headers=h).json()["graphs"]
    assert "graph TD" in g["chat"] and "ask_user" in g["learn"]
    assert client.get("/admin/graphs", headers=H(client, "priya@demo.com", ws)).status_code == 403   # owner only
    j = client.post("/admin/jobs/freshness", headers=h, json={"days_ahead": 0, "dry_run": True}).json()
    assert {"changes", "purged", "threads_purged", "llm_checks"} <= set(j)
    assert db.jobs.find_one({"_id": "freshness"})["last_result"]
    assert client.post("/admin/demo-mode", headers=h, json={"ask_on_conflict": True}).json()["ask_on_conflict"] is True
    assert client.get("/analytics/summary", headers=h).status_code == 200


def test_demo_mode_makes_real_contradictions_ask_a_human(client, ws, mem):
    mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    h = H(client, "alex@demo.com", ws)
    client.post("/admin/demo-mode", headers=h, json={"ask_on_conflict": True})
    chat(client, h, "We switched from REST to GraphQL for all endpoints.")           # confident (0.85) contradiction
    assert wait_for(lambda: db.memory_events.find_one({"workspace_id": ws["id"], "action": "needs_user_choice", "resolved": False}))


def test_live_event_reaches_workspace_subscribers(client, ws):
    """Decision events travel Change Stream -> broadcaster, so another process (MCP) can open a decision too."""
    from app.services import decisions_service as d
    from app.services.events_service import broadcaster
    q = broadcaster.subscribe(ws["id"], ws["priya"])
    time.sleep(1.5)  # let the change stream attach
    d.open_decision(ws["id"], ws["alex"], f"learn:{ws['id']}:x:y", {"kind": "conflict", "question": "q"})
    got = []
    t = time.time()
    while time.time() - t < 6 and not got:
        try:
            got.append(q.get(timeout=1))
        except Exception:
            pass
    broadcaster.unsubscribe(ws["id"], q)
    assert got and got[0]["kind"] == "needs_user_choice"


def test_mcp_tools_use_the_graphs(ws, mem, monkeypatch):
    import hashlib
    import importlib
    import os
    os.environ["TEAMMIND_TOKEN"] = "tm_testtoken"
    db.api_tokens.insert_one({"workspace_id": ws["id"], "user_id": ws["alex"], "label": "claude-code", "scope": "readwrite",
                              "token_hash": hashlib.sha256(b"tm_testtoken").hexdigest()})
    srv = importlib.import_module("mcp_server.server")
    old = mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    hits = srv.recall("which API style do we use?", k=3)
    assert hits and hits[0]["id"] == str(old["_id"])
    assert srv.remember("We deploy on Thursdays.", type="decision", topic="deploys")["status"] == "saved"
    r = srv.remember("Maybe we switched to GraphQL for all endpoints.", type="decision", topic="api style")
    assert r["status"] == "needs_user_choice" and r["thread_id"].startswith(f"learn:{ws['id']}:")
    c = srv.correct(str(old["_id"]), "We use gRPC for all endpoints.", "agent fix")
    assert c["status"] == "superseded"
