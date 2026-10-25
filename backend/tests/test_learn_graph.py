import json

from langgraph.types import Command

from app.db.mongo import db
from app.graph import runners, threads
from app.graph.learn_graph import build_learn_graph
from app.graph.registry import checkpointer, learn_graph


def learn(ws, text, **kw):
    return runners.start_learn(ws["id"], ws["alex"], user_text=text, answer_text="", conv_id="t", **kw)


def active(ws, **q):
    return list(db.memories.find({"workspace_id": ws["id"], "status": "active", **q}))


def test_new_fact_is_saved(ws):
    r = learn(ws, "Remember: we cannot use paid APIs.")
    assert r["status"] == "done" and r["results"][0]["status"] == "saved"
    assert len(active(ws)) == 1


def test_small_talk_saves_nothing(ws):
    r = learn(ws, "thanks, that was great")
    assert r["status"] == "done" and r["results"] == [] and active(ws) == []


def test_contradiction_supersedes_old_memory(ws, mem):
    old = mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    r = learn(ws, "We switched from REST to GraphQL for all endpoints.")
    assert r["results"][0]["status"] == "superseded"
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "superseded"
    new = db.memories.find_one({"_id": old["_id"]})["superseded_by"]
    assert db.memories.find_one({"_id": new})["supersedes"] == old["_id"]


def test_duplicate_reinforces_instead_of_saving_again(ws, mem):
    old = mem("We cannot use paid APIs.", type="constraint", topic="budget")
    r = learn(ws, "Remember: we cannot use paid APIs.")
    assert r["results"][0]["status"] == "reinforced"
    assert db.memories.find_one({"_id": old["_id"]})["reinforcement_count"] == 1
    assert len(active(ws)) == 1


def test_secret_candidate_is_skipped_never_saved(ws):
    r = runners.start_learn(ws["id"], ws["alex"], queue=[{"content": "deploy key is sk-TESTTESTTESTTESTTESTTEST", "type": "fact"},
                                                          {"content": "We deploy on Thursdays.", "type": "decision"}], conv_id="t")
    assert [x["status"] for x in r["results"]] == ["blocked", "saved"]   # the loop moved on to the next candidate
    docs = list(db.memories.find({"workspace_id": ws["id"]}, {"embedding": 0}))
    assert "sk-TEST" not in json.dumps(docs, default=str)


def test_loop_handles_several_candidates_and_cap(ws):
    q = [{"content": f"We decided to use tool number {i} for task {i}.", "type": "decision", "topic": f"tool{i}"} for i in range(12)]
    r = runners.start_learn(ws["id"], ws["alex"], queue=q, conv_id="t", max_candidates=12)   # 12 candidates > default recursion limit of 25 steps
    assert r["status"] == "done" and len(r["results"]) == 12


def test_unsure_judge_pauses_then_resume_use_new(ws, mem):
    old = mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    r = learn(ws, "Maybe we switched to GraphQL for all endpoints.")           # fake judge: confidence 0.4
    assert r["status"] == "needs_user_choice" and r["pending"][0]["kind"] == "conflict"
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "active"      # nothing written while paused
    assert db.memory_events.count_documents({"action": "needs_user_choice", "thread_id": r["thread_id"], "resolved": False}) == 1
    assert threads.interrupts_of(learn_graph, {"configurable": {"thread_id": r["thread_id"]}})
    r2 = runners.resume(ws["id"], ws["alex"], r["thread_id"], "use_new")
    assert r2["status"] == "done" and r2["results"][-1]["status"] == "superseded"
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "superseded"
    assert len(active(ws)) == 1                                                  # exactly one memory written


def test_resume_keep_old_and_keep_both(ws, mem):
    old = mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    r = learn(ws, "Maybe we switched to GraphQL for all endpoints.")
    r2 = runners.resume(ws["id"], ws["alex"], r["thread_id"], "keep_old")
    assert r2["results"][-1]["status"] == "kept_old" and len(active(ws)) == 1
    r = learn(ws, "Perhaps we switched to GraphQL for all endpoints.")
    runners.resume(ws["id"], ws["alex"], r["thread_id"], "keep_both")
    assert len(active(ws)) == 2 and db.memories.find_one({"_id": old["_id"]})["status"] == "active"


def test_paused_run_survives_a_restart(ws, mem):
    """A brand-new graph object (= a restarted server) resumes the same thread from MongoDB."""
    old = mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    r = learn(ws, "Maybe we switched to GraphQL for all endpoints.")
    fresh = build_learn_graph(checkpointer)
    out = fresh.invoke(Command(resume="use_new"), {"configurable": {"thread_id": r["thread_id"]}, "recursion_limit": 100})
    assert out["results"][-1]["status"] == "superseded"
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "superseded"


def test_paused_state_is_json_safe_and_has_no_vectors(ws, mem):
    mem("We use REST for all endpoints.", topic="api style", tags=["api", "rest"])
    r = learn(ws, "Maybe we switched to GraphQL for all endpoints.")
    vals = learn_graph.get_state({"configurable": {"thread_id": r["thread_id"]}}).values
    json.dumps(vals)                                                             # raises if ObjectId / datetime / numpy sneaked in
    assert "embedding" not in json.dumps(vals)


def test_force_supersede_for_correct(ws, mem):
    old = mem("Demo is on Friday.", type="fact", topic="schedule")
    r = runners.start_learn(ws["id"], ws["alex"], force={"target_id": str(old["_id"]), "content": "Demo is on Saturday.", "reason": "fix"},
                            conv_id="t", notify=False)
    assert r["results"][0]["status"] == "superseded"
    assert db.memories.find_one({"_id": old["_id"]})["status"] == "superseded"


def test_private_conflict_question_is_private(ws, mem):
    mem("Alex prefers REST style answers.", type="preference", topic="api style", tags=["api", "rest"], scope="private")
    r = runners.start_learn(ws["id"], ws["alex"], queue=[{"content": "Maybe prefers GraphQL style answers.", "type": "preference",
                                                           "topic": "api style", "scope": "private", "tags": ["api"]}], conv_id="t")
    assert r["status"] == "needs_user_choice"
    from app.services import decisions_service as d
    assert len(d.pending(ws["id"], ws["alex"])) == 1 and d.pending(ws["id"], ws["priya"]) == []
