"""The checkpointer saves the state of every graph run after each step, in the same Atlas cluster.
That is what makes pause/resume (interrupt) and crash recovery work."""
import logging

from app.core.config import settings

log = logging.getLogger("teammind.graph")


def make_checkpointer():
    """Returns (checkpointer, kind). Falls back to memory when MongoDB is unreachable (state is then lost on restart)."""
    if settings.graph_checkpointer != "memory":
        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver
            from app.db.mongo import client
            return MongoDBSaver(client, db_name=settings.mongodb_db), "mongodb"
        except Exception as e:  # MongoDB down at startup, or LangGraph package mismatch
            log.error("MongoDBSaver unavailable (%s). Falling back to in-memory checkpoints.", e)
    from langgraph.checkpoint.memory import InMemorySaver
    return InMemorySaver(), "memory"
