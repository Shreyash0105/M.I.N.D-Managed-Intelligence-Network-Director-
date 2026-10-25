"""Graph 1: the Chat graph (foreground, the user waits) and the reusable Retrieve subgraph.

START -> guard -> (blocked_reply | retrieve | responder) -> finalize -> END"""
from langgraph.graph import END, START, StateGraph

from app.graph import chat_nodes as n
from app.graph.state import ChatState


def build_retrieve_graph():
    """planner -> retriever. Used by the Chat graph AND by MCP recall (which passes a ready plan and skips the planner)."""
    g = StateGraph(ChatState)
    g.add_node("planner", n.planner_node)
    g.add_node("retriever", n.retriever_node)
    g.add_conditional_edges(START, lambda s: "retriever" if s.get("plan") else "planner", ["planner", "retriever"])
    g.add_conditional_edges("planner", lambda s: "retriever" if s["plan"]["need_memory"] else "done",
                            {"retriever": "retriever", "done": END})
    g.add_edge("retriever", END)
    return g.compile()


retrieve_graph = build_retrieve_graph()


def build_chat_graph(checkpointer):
    g = StateGraph(ChatState)
    g.add_node("guard", n.guard_node)
    g.add_node("blocked_reply", n.blocked_node)
    g.add_node("retrieve", n.retrieve_node)
    g.add_node("responder", n.responder_node)
    g.add_node("finalize", n.finalize_node)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", n.after_guard, {"blocked": "blocked_reply", "retrieve": "retrieve", "respond": "responder"})
    g.add_edge("retrieve", "responder")
    g.add_edge("responder", "finalize")
    g.add_edge("blocked_reply", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
