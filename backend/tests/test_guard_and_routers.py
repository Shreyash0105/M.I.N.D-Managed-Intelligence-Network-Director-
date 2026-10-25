"""Guard rules and the router functions of every graph (no LLM, no database needed for the routers)."""
from app.agents import guard
from app.graph import chat_nodes, learn_nodes, reflect_nodes


def test_guard_blocks_keys_and_redacts_email():
    assert guard.check("my key is sk-TESTTESTTESTTESTTESTTEST")["action"] == "block"
    g = guard.check("mail me at a.b@example.com")
    assert g["action"] == "save_private" and "[REDACTED:email]" in g["clean_text"]
    assert guard.check("We use FastAPI")["action"] == "allow"


def test_chat_router_after_guard():
    assert chat_nodes.after_guard({"guard": {"action": "block"}, "memory_on": True}) == "blocked"
    assert chat_nodes.after_guard({"guard": {"action": "allow"}, "memory_on": True}) == "retrieve"
    assert chat_nodes.after_guard({"guard": {"action": "allow"}, "memory_on": False}) == "respond"


def test_learn_routers():
    v = lambda rel, conf, tid="x": {"verdict": {"relation": rel, "confidence": conf, "target_id": tid}}  # noqa: E731
    assert learn_nodes.after_judge(v("contradicts", 0.9)) == "supersede"
    assert learn_nodes.after_judge(v("refines", 0.9)) == "supersede"
    assert learn_nodes.after_judge(v("duplicate", 0.9)) == "reinforce"
    assert learn_nodes.after_judge(v("unrelated", 0.9)) == "save_new"
    assert learn_nodes.after_judge(v("contradicts", 0.5)) == "ask_user"        # unsure -> ask a human
    assert learn_nodes.after_judge(v("unrelated", 0.3)) == "save_new"          # nothing to ask about
    assert learn_nodes.after_record({"queue": [1]}) == "pick_next"
    assert learn_nodes.after_record({"queue": []}) == "publish_summary"
    assert learn_nodes.entry({"force": {"target_id": "a"}}) == "force_supersede"
    assert learn_nodes.entry({"queue": [{}]}) == "pick_next"
    assert learn_nodes.entry({"user_text": "hi"}) == "extractor"
    assert learn_nodes.after_guard({"guard": {"action": "block"}}) == "skip"
    assert learn_nodes.after_find({"similar": []}) == "save_new"


def test_reflection_routers():
    assert reflect_nodes.after_validate({"lesson": {"content": "x" * 20}, "require_approval": True}) == "approval"
    assert reflect_nodes.after_validate({"lesson": {"content": "x" * 20}}) == "save_strategy"
    assert reflect_nodes.after_validate({"lesson": {}, "tries": 1}) == "reflect"
    assert reflect_nodes.after_validate({"lesson": {}, "tries": 2}) == "skip_group"
