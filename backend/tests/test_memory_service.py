import pytest
from fastapi import HTTPException

from app.db.mongo import db
from app.services import memory_service as memory


def test_create_and_supersede_is_atomic_and_linked(ws, mem):
    old = mem("We use REST for all endpoints.", topic="api style")
    new = memory.supersede(ws["id"], ws["alex"], old["_id"], {"content": "We use GraphQL for all endpoints.", "type": "decision"},
                           "test", "changed")
    o = db.memories.find_one({"_id": old["_id"]})
    assert o["status"] == "superseded" and o["superseded_by"] == new["_id"]
    assert db.memories.find_one({"_id": new["_id"]})["supersedes"] == old["_id"]
    assert db.memory_events.count_documents({"memory_id": str(old["_id"]), "action": "superseded"}) == 1


def test_soft_delete_then_hard_delete_keeps_no_text_in_audit(ws, mem):
    m = mem("secret-ish launch date is 5 May", type="fact")
    memory.soft_delete(ws["id"], ws["alex"], m["_id"])
    assert db.memories.find_one({"_id": m["_id"]})["status"] == "deleted"
    memory.hard_delete(ws["id"], ws["alex"], m["_id"])
    assert db.memories.find_one({"_id": m["_id"]}) is None
    ev = db.memory_events.find_one({"memory_id": str(m["_id"]), "action": "purged"})
    assert ev and "launch" not in str(ev)


def test_wrong_workspace_cannot_touch_memory(ws, mem):
    m = mem("only for workspace A")
    with pytest.raises(HTTPException):
        memory.soft_delete("0123456789abcdef01234567", ws["alex"], m["_id"])
    assert db.memories.find_one({"_id": m["_id"]})["status"] == "active"


def test_private_memory_hidden_from_teammate(ws, mem):
    m = mem("Alex likes short answers", type="preference", scope="private")
    with pytest.raises(HTTPException):
        memory.get(ws["id"], ws["priya"], str(m["_id"]))
    assert memory.get(ws["id"], ws["alex"], str(m["_id"]))["id"] == str(m["_id"])
