"""Bookkeeping for graph threads: who owns a thread (tenant check), which ones are paused, which can be purged."""
from app.core.util import utcnow
from app.db.mongo import db


def chat_thread(ws: str, conversation_id: str) -> str:
    return f"chat:{ws}:{conversation_id}"


def learn_thread(ws: str, conversation_id: str, msg_id: str) -> str:
    return f"learn:{ws}:{conversation_id}:{msg_id}"


def reflect_thread(ws: str, run_id: str) -> str:
    return f"reflect:{ws}:{run_id}"


def kind_of(thread_id: str) -> str:
    return thread_id.split(":", 1)[0]


def belongs_to(ws: str, thread_id: str) -> bool:
    """Tenant check is a simple prefix check because every thread id contains its workspace."""
    return any(thread_id.startswith(f"{k}:{ws}:") for k in ("chat", "learn", "reflect"))


def register(thread_id: str, ws: str, uid: str, ephemeral: bool = False):
    db.graph_threads.update_one({"_id": thread_id}, {"$set": {"workspace_id": ws, "user_id": uid, "kind": kind_of(thread_id),
                                                              "ephemeral": ephemeral, "updated_at": utcnow()},
                                                     "$setOnInsert": {"created_at": utcnow(), "pending": False}}, upsert=True)


def set_pending(thread_id: str, pending: bool):
    db.graph_threads.update_one({"_id": thread_id}, {"$set": {"pending": pending, "updated_at": utcnow()}})


def interrupts_of(graph, cfg) -> list:
    """Values of the interrupt() calls the run is currently paused on ([] when it finished)."""
    try:
        st = graph.get_state(cfg)
    except Exception:
        return []
    return [i.value for t in st.tasks for i in getattr(t, "interrupts", ())]
