"""Graph 4: the Freshness graph (hourly). Fan-out: four jobs start together, a join node waits for all and summarizes."""
from langgraph.graph import END, START, StateGraph

from app.graph import fresh_nodes as n
from app.graph.state import FreshState


def build_freshness_graph():
    g = StateGraph(FreshState)
    jobs = [("decay_archive", n.decay_archive), ("stale_flag", n.stale_flag),
            ("purge_deleted", n.purge_deleted), ("purge_threads", n.purge_threads)]
    for name, fn in jobs:
        g.add_node(name, fn)
        g.add_edge(START, name)                      # four nodes start together
    g.add_node("summarize", n.summarize)
    g.add_edge([name for name, _ in jobs], "summarize")  # wait for all four (join)
    g.add_edge("summarize", END)
    return g.compile()                               # no human step, so no checkpointer needed
