"""Compiles every graph ONCE, at import (= server start). Everything else imports the compiled graphs from here."""
from app.graph.checkpointer import make_checkpointer
from app.graph.chat_graph import build_chat_graph, retrieve_graph
from app.graph.freshness_graph import build_freshness_graph
from app.graph.learn_graph import build_learn_graph
from app.graph.reflection_graph import build_reflection_graph

checkpointer, checkpointer_kind = make_checkpointer()
chat_graph = build_chat_graph(checkpointer)
learn_graph = build_learn_graph(checkpointer)
reflection_graph = build_reflection_graph(checkpointer)
freshness_graph = build_freshness_graph()

GRAPHS = {"chat": chat_graph, "retrieve": retrieve_graph, "learn": learn_graph,
          "reflection": reflection_graph, "freshness": freshness_graph}


def mermaid() -> dict:
    """Mermaid text of every graph (Settings -> Workflow graphs, slides, and the snapshot test)."""
    return {name: g.get_graph().draw_mermaid() for name, g in GRAPHS.items()}
