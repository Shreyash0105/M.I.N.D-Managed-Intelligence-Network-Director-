"""Tests run against a separate database (teammind_test) with the fake LLM and hash embeddings: fast, free, repeatable.
Needs a MongoDB replica set (Atlas, or a local single-node replica set). Set TEST_MONGODB_URI to point at it."""
import os
import sys
from pathlib import Path

os.environ["MONGODB_URI"] = os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017/?directConnection=true")
os.environ["MONGODB_DB"] = "teammind_test"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["GRAPH_CHECKPOINTER"] = "mongo"
os.environ["RATE_LIMIT_PER_MIN"] = "1000"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.db.mongo import client, db  # noqa: E402

# Drop at import time: before any test module imports the graph registry (which creates the checkpoint collections).
client.drop_database("teammind_test")


@pytest.fixture(scope="session", autouse=True)
def _indexes():
    from app.db import indexes
    indexes.ensure_normal_indexes()
    yield
    client.drop_database("teammind_test")


@pytest.fixture
def ws():
    """A fresh workspace with an owner (Alex) and a member (Priya)."""
    from app.core.util import utcnow
    from app.services import seed
    alex, priya = seed.create_demo_users()
    r = db.workspaces.insert_one({"name": "T", "owner_id": str(alex["_id"]), "created_at": utcnow(),
                                  "members": [{"user_id": str(alex["_id"]), "role": "owner"},
                                              {"user_id": str(priya["_id"]), "role": "member"}], "settings": {}})
    return {"id": str(r.inserted_id), "alex": str(alex["_id"]), "priya": str(priya["_id"])}


@pytest.fixture
def mem(ws):
    """Helper to create a memory straight through the memory service."""
    from app.services import memory_service as memory

    def make(content, type="decision", topic="general", tags=None, uid=None, **kw):
        return memory.create_memory(ws["id"], uid or ws["alex"], {"content": content, "type": type, "topic": topic,
                                                                  "tags": tags or [], **kw}, actor="test")
    return make
