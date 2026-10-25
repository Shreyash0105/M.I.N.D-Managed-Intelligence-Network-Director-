import logging
from pymongo.operations import SearchIndexModel
from app.db.mongo import db
from app.core.config import settings

log = logging.getLogger("teammind.indexes")

VECTOR_DEF = {
    "fields": [
        {"type": "vector", "path": "embedding", "numDimensions": settings.embedding_dims, "similarity": "cosine"},
        {"type": "filter", "path": "workspace_id"},
        {"type": "filter", "path": "status"},
        {"type": "filter", "path": "scope"},
        {"type": "filter", "path": "type"},
        {"type": "filter", "path": "user_id"},
    ]
}
TEXT_DEF = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "content": {"type": "string"},
            "topic": {"type": "string"},
            "tags": {"type": "string"},
            "workspace_id": {"type": "token"},
            "status": {"type": "token"},
        },
    }
}


def ensure_normal_indexes():
    m = db.memories
    m.create_index([("workspace_id", 1), ("status", 1), ("updated_at", -1)], name="ws_status_updated")
    m.create_index([("workspace_id", 1), ("tags", 1)], name="ws_tags")
    m.create_index([("workspace_id", 1), ("topic", 1)], name="ws_topic")
    # TTL: Mongo deletes the document when expires_at passes (checked ~every 60s).
    # Documents where expires_at is null/missing are never deleted.
    m.create_index("expires_at", expireAfterSeconds=0, name="ttl_expires_at")
    db.users.create_index("email", unique=True)
    db.memory_events.create_index([("memory_id", 1), ("ts", -1)])
    db.memory_events.create_index([("workspace_id", 1), ("ts", -1)])
    db.api_tokens.create_index("token_hash", unique=True)
    db.conversations.create_index([("workspace_id", 1), ("user_id", 1), ("updated_at", -1)])
    db.agent_runs.create_index([("workspace_id", 1), ("ts", -1)])
    db.agent_runs.create_index([("workspace_id", 1), ("conversation_id", 1), ("ts", -1)])
    db.memory_events.create_index(
        [("workspace_id", 1), ("action", 1), ("resolved", 1)],
        name="ev_ws_action_resolved",
    )  # pending decisions lookup
    db.graph_threads.create_index([("workspace_id", 1), ("updated_at", -1)])


def ensure_search_indexes():
    have = {i["name"] for i in db.memories.list_search_indexes()}
    if "memory_vector" not in have:
        db.memories.create_search_index(SearchIndexModel(definition=VECTOR_DEF, name="memory_vector", type="vectorSearch"))
    if "memory_text" not in have:
        db.memories.create_search_index(SearchIndexModel(definition=TEXT_DEF, name="memory_text", type="search"))


def index_status() -> dict:
    try:
        return {i["name"]: i.get("status", "UNKNOWN") for i in db.memories.list_search_indexes()}
    except Exception as e:
        return {"error": f"Atlas Search not available: {e}"}


def ensure_all():
    ensure_normal_indexes()
    try:
        ensure_search_indexes()
    except Exception as e:
        log.warning("Could not create search indexes (retrieval will use local fallback): %s", e)
