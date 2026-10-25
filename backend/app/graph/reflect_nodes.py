"""Reflection graph nodes: select_groups -> pick_group -> reflect -> validate -> (retry | approval | save) -> next group."""
from typing import Literal

from langgraph.types import Command, interrupt

from app.agents import reflection
from app.core.config import settings
from app.graph import threads
from app.graph.tracing import traced
from app.services import events_service as ev

MAX_TRIES = 2


@traced("select_groups")
def select_groups_node(s):
    groups = reflection.select_groups(s["workspace_id"])
    return {"groups": groups, "groups_checked": len(groups), "trace": [{"node": "select_groups", "n": len(groups)}]}


@traced("pick_group")
def pick_group(s):
    g = s["groups"]
    return {"current": g[0], "groups": g[1:], "raw": {}, "lesson": {}, "tries": 0}


@traced("reflect", model=settings.llm_model_main)
def reflect_node(s):
    return {"raw": reflection.reflect(s["current"]) or {}, "tries": s.get("tries", 0) + 1}


@traced("validate")
def validate_node(s):
    lesson = reflection.validate(s.get("raw"))
    return {"lesson": lesson or {}, "trace": [{"node": "validate", "ok": bool(lesson), "try": s.get("tries")}]}


@traced("approval")
def approval(s) -> Command[Literal["save_strategy", "skip_group"]]:
    """Optional human step: a lesson becomes team knowledge only after a person approves it."""
    ok = interrupt({"kind": "lesson", "question": "Save this lesson as a strategy memory?", "text": s["lesson"]["content"],
                    "topic": s["current"]["topic"], "sources": s["current"]["items"][:8], "private": False})
    return Command(goto="save_strategy" if ok == "approve" else "skip_group")


@traced("save_strategy")
def save_strategy(s):
    made = reflection.save(s["workspace_id"], s["user_id"], s["current"], s["lesson"])  # strategy + derived_from + lowered sources
    return {"created": [made], "trace": [{"node": "save_strategy", "id": made["id"]}]}


@traced("skip_group")
def skip_group(s):
    return {"trace": [{"node": "skip_group", "topic": s["current"]["topic"]}]}


@traced("finish")
def finish(s):
    if s.get("thread_id"):
        threads.set_pending(s["thread_id"], False)
    return {"trace": [{"node": "finish", "created": len(s.get("created") or [])}]}


def after_select(s):
    return "pick_group" if s.get("groups") else "end"


def after_validate(s):
    if s.get("lesson"):
        return "approval" if s.get("require_approval") else "save_strategy"
    return "reflect" if s.get("tries", 0) < MAX_TRIES else "skip_group"  # retry up to 2 times, then give up on this group


def after_group(s):
    return "pick_group" if s.get("groups") else "finish"
