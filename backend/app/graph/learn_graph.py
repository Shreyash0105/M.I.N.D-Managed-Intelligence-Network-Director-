"""Graph 2: the Learn graph (background). Loops over memory candidates one by one and pauses for a human when unsure.

START -> (extractor | pick_next | force_supersede)
pick_next -> guard_candidate -> find_similar -> judge -> save_new | reinforce | supersede | ask_user(interrupt)
every outcome -> record_result -> (pick_next | publish_summary) -> END"""
from langgraph.graph import END, START, StateGraph

from app.graph import learn_nodes as n
from app.graph.state import LearnState


def build_learn_graph(checkpointer):
    g = StateGraph(LearnState)
    for name, fn in [("extractor", n.extractor_node), ("pick_next", n.pick_next), ("guard_candidate", n.guard_candidate),
                     ("find_similar", n.find_similar), ("judge", n.judge_node), ("save_new", n.save_new_node),
                     ("reinforce", n.reinforce_node), ("supersede", n.supersede_node),
                     ("force_supersede", n.force_supersede_node), ("skip", n.skip_node),
                     ("record_result", n.record_result), ("publish_summary", n.publish_summary)]:
        g.add_node(name, fn)
    g.add_node("ask_user", n.ask_user, destinations=("supersede", "record_result", "save_new"))
    g.add_conditional_edges(START, n.entry, ["extractor", "pick_next", "force_supersede"])
    g.add_conditional_edges("extractor", n.after_extract, {"pick_next": "pick_next", "end": END})
    g.add_edge("pick_next", "guard_candidate")
    g.add_conditional_edges("guard_candidate", n.after_guard, ["skip", "find_similar"])
    g.add_conditional_edges("find_similar", n.after_find, ["judge", "save_new"])
    g.add_conditional_edges("judge", n.after_judge, ["save_new", "reinforce", "supersede", "ask_user"])
    for name in ("save_new", "reinforce", "supersede", "force_supersede", "skip"):
        g.add_edge(name, "record_result")
    g.add_conditional_edges("record_result", n.after_record, ["pick_next", "publish_summary"])  # <- the LOOP
    g.add_edge("publish_summary", END)
    return g.compile(checkpointer=checkpointer)
