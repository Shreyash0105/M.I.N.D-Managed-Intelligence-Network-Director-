import json

from app.db.mongo import db
from app.graph import runners
from app.graph.registry import GRAPHS, freshness_graph, mermaid


def test_reflection_graph_creates_strategy_from_three_outcomes(ws, mem):
    ids = [mem(t, type="outcome", topic="deployment", tags=["deploy"])["_id"] for t in
           ("Friday night deploy failed: tokens expired.", "Friday deploy rolled back: env vars missing.", "Late Friday deploy broke CORS.")]
    r = runners.run_reflection(ws["id"], ws["alex"], require_approval=False)
    assert r["status"] == "done" and len(r["created"]) == 1
    s = db.memories.find_one({"workspace_id": ws["id"], "type": "strategy"})
    assert set(s["derived_from"]) == set(ids) and s["confidence"] <= 0.7
    assert db.memories.find_one({"_id": ids[0]})["importance"] < 0.6              # sources lowered
    assert runners.run_reflection(ws["id"], ws["alex"])["created"] == []           # already consolidated


def test_reflection_needs_enough_memories(ws, mem):
    mem("one", type="outcome", topic="deployment")
    assert runners.run_reflection(ws["id"], ws["alex"])["groups_checked"] == 0


def test_reflection_approval_pause_and_resume(ws, mem):
    for t in ("a failed deploy one", "a failed deploy two", "a failed deploy three"):
        mem(t, type="outcome", topic="deployment")
    r = runners.run_reflection(ws["id"], ws["alex"], require_approval=True)
    assert r["status"] == "needs_user_choice" and r["pending"][0]["kind"] == "lesson"
    assert db.memories.count_documents({"workspace_id": ws["id"], "type": "strategy"}) == 0
    r2 = runners.resume(ws["id"], ws["alex"], r["thread_id"], "approve")
    assert r2["status"] == "done" and db.memories.count_documents({"workspace_id": ws["id"], "type": "strategy"}) == 1


def test_reflection_reject_saves_nothing(ws, mem):
    for t in ("a failed deploy one", "a failed deploy two", "a failed deploy three"):
        mem(t, type="outcome", topic="deployment")
    r = runners.run_reflection(ws["id"], ws["alex"], require_approval=True)
    runners.resume(ws["id"], ws["alex"], r["thread_id"], "reject")
    assert db.memories.count_documents({"workspace_id": ws["id"], "type": "strategy"}) == 0


def test_reflection_retries_bad_lesson_then_gives_up(ws, mem, monkeypatch):
    for t in ("a failed deploy one", "a failed deploy two", "a failed deploy three"):
        mem(t, type="outcome", topic="deployment")
    calls = []
    from app.agents import reflection
    monkeypatch.setattr(reflection, "reflect", lambda g: calls.append(1) or {"content": "x"})   # invalid (too short) every time
    r = runners.run_reflection(ws["id"], ws["alex"])
    assert len(calls) == 2 and r["created"] == []                                  # retry max 2, then stop


def test_freshness_graph_runs_four_jobs_in_parallel_then_joins(ws, mem):
    from datetime import timedelta
    from app.core.util import utcnow
    mem("Demo day is on Saturday at 3 pm.", type="fact", topic="schedule", importance=0.6)
    mem("We cannot use paid APIs.", type="constraint", topic="budget")             # constraints never decay
    out = freshness_graph.invoke({"shift_days": 400, "workspace_id": ws["id"], "dry_run": False, "results": []})
    jobs = sorted(r["job"] for r in out["results"])
    assert jobs == ["decay_archive", "purge_deleted", "purge_threads", "stale_flag"]
    changed = {c["to"] for c in out["summary"]["changes"]}
    assert changed == {"archived"}                                                  # decay and stale never double-handle a memory
    assert db.memories.count_documents({"workspace_id": ws["id"], "status": "archived"}) == 1
    assert db.memories.count_documents({"workspace_id": ws["id"], "status": "active"}) == 1


def test_freshness_dry_run_changes_nothing_and_flags_stale(ws, mem):
    mem("Demo day is on Saturday at 3 pm.", type="fact", topic="schedule", importance=0.95)
    r = runners.run_freshness(days_ahead=30, ws=ws["id"], dry_run=True)
    assert r["changes"] and r["changes"][0]["to"] == "stale" and r["dry_run"] is True
    assert db.memories.find_one({"workspace_id": ws["id"]})["status"] == "active"
    runners.run_freshness(days_ahead=30, ws=ws["id"])
    assert db.memories.find_one({"workspace_id": ws["id"]})["status"] == "stale"


def test_purge_threads_deletes_old_finished_threads_but_not_paused_ones(ws):
    from datetime import timedelta
    from app.core.util import utcnow
    from app.graph import threads
    for tid, pending in ((f"chat:{ws['id']}:old", False), (f"learn:{ws['id']}:c:paused", True)):
        threads.register(tid, ws["id"], ws["alex"])
        db.graph_threads.update_one({"_id": tid}, {"$set": {"updated_at": utcnow() - timedelta(days=30), "pending": pending}})
    r = runners.run_freshness(ws=ws["id"])
    assert r["threads_purged"] == 1
    assert db.graph_threads.find_one({"_id": f"chat:{ws['id']}:old"}) is None
    assert db.graph_threads.find_one({"_id": f"learn:{ws['id']}:c:paused"}) is not None


def test_graph_snapshot_matches_saved_mermaid():
    """If this fails someone changed a workflow. If it was on purpose: UPDATE_SNAPSHOTS=1 pytest tests/test_other_graphs.py"""
    import os
    from pathlib import Path
    path = Path(__file__).parent / "snapshots" / "graphs.json"
    current = mermaid()
    assert set(current) == {"chat", "retrieve", "learn", "reflection", "freshness"} == set(GRAPHS)
    if os.getenv("UPDATE_SNAPSHOTS") or not path.exists():
        path.write_text(json.dumps(current, indent=1, sort_keys=True))
    saved = json.loads(path.read_text())
    for name, text in current.items():
        # the order of parallel edges is not stable, compare as sets of lines
        assert sorted(text.splitlines()) == sorted(saved[name].splitlines()), name
