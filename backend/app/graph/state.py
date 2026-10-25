"""Shared state classes for the four graphs.

Rules (see the build guide): state is saved in MongoDB by the checkpointer, so keep it JSON-safe:
str ids (no ObjectId), ISO strings (no datetime), short texts, and never embeddings or secrets.
A *reducer* tells LangGraph how to merge a node's update into the state (append instead of replace)."""
import operator
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

RESET = {"__reset__": True}  # put it first in a trace update to start a fresh list (new turn in the same thread)


def append_or_reset(old, new):
    """Reducer for trace lists. Appends; a leading RESET marker starts a new list (per-turn trace in a long thread)."""
    new = list(new or [])
    if new and isinstance(new[0], dict) and new[0].get("__reset__"):
        return new[1:]
    return list(old or []) + new


class ChatState(TypedDict, total=False):
    # inputs: set by the API from the verified user, never from the request body
    workspace_id: str
    user_id: str
    conversation_id: str          # empty for ephemeral (Compare) runs
    user_text: str
    memory_on: bool
    k: int                        # how many memories to retrieve (MCP recall may change it)
    # working notebook
    messages: Annotated[list, add_messages]   # chat turns; the reducer APPENDS instead of replacing
    guard: dict
    clean_text: str
    plan: dict
    history: list                 # earlier turns as {role, text}; only used inside the Retrieve subgraph
    hits: list                    # public, JSON-safe memory dicts (id, ref, type, content, scores, ...)
    retrieval_mode: str
    types_filter: list
    track: bool
    answer: str
    used_memory_ids: list
    llm_error: str
    memory_only: bool             # LLM was down: we returned the top memories without a written answer
    started_at: float
    # audit
    trace: Annotated[list, append_or_reset]   # every node appends one entry; finalize writes agent_runs


class LearnState(TypedDict, total=False):
    workspace_id: str
    user_id: str
    agent_id: str
    actor: str                    # who gets credit in the audit trail: "agent", "agent:<label>" or a user id
    thread_id: str
    conversation_id: str
    user_text: str
    answer_text: str
    notify: bool                  # publish a toast per result (chat runs); API/MCP runs return results instead
    ask_on_conflict: bool         # demo mode: always ask the human when the judge says "contradicts"
    max_candidates: int
    truncated: int                # how many candidates were dropped by the cap
    queue: list
    current: dict
    guard: dict
    similar: list
    verdict: dict
    force: dict                   # {"target_id", "content", "reason"} for MCP correct / PATCH
    started_at: float
    results: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


class ReflectState(TypedDict, total=False):
    workspace_id: str
    user_id: str
    thread_id: str
    require_approval: bool
    groups: list
    current: dict
    raw: dict
    lesson: dict
    tries: int
    groups_checked: int
    created: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


class FreshState(TypedDict, total=False):
    shift_days: int               # "time machine": pretend today is +N days
    workspace_id: str
    dry_run: bool
    results: Annotated[list, operator.add]    # the four parallel jobs all append here
    summary: dict
