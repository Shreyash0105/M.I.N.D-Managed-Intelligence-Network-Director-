"""Graph 3: the Reflection graph (nightly, or the Consolidate button). Has a validate-retry loop and an optional human approval step."""
from langgraph.graph import END, START, StateGraph

from app.graph import reflect_nodes as n
from app.graph.state import ReflectState


def build_reflection_graph(checkpointer):
    g = StateGraph(ReflectState)
    for name, fn in [("select_groups", n.select_groups_node), ("pick_group", n.pick_group), ("reflect", n.reflect_node),
                     ("validate", n.validate_node), ("save_strategy", n.save_strategy), ("skip_group", n.skip_group),
                     ("finish", n.finish)]:
        g.add_node(name, fn)
    g.add_node("approval", n.approval, destinations=("save_strategy", "skip_group"))
    g.add_edge(START, "select_groups")
    g.add_conditional_edges("select_groups", n.after_select, {"pick_group": "pick_group", "end": END})
    g.add_edge("pick_group", "reflect")
    g.add_edge("reflect", "validate")
    g.add_conditional_edges("validate", n.after_validate, ["approval", "save_strategy", "reflect", "skip_group"])
    g.add_conditional_edges("save_strategy", n.after_group, ["pick_group", "finish"])
    g.add_conditional_edges("skip_group", n.after_group, ["pick_group", "finish"])
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)
