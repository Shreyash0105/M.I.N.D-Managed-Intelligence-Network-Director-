"""Freshness graph nodes: four independent jobs run in parallel, then one node joins and summarizes."""
from app.agents import freshness
from app.graph.tracing import traced


def _args(s):
    return s.get("workspace_id"), int(s.get("shift_days") or 0), bool(s.get("dry_run"))


@traced("decay_archive")
def decay_archive(s):
    r = freshness.decay_archive(*_args(s))
    return {"results": [{"job": "decay_archive", **r}]}


@traced("stale_flag")
def stale_flag(s):
    r = freshness.stale_flag(*_args(s))
    return {"results": [{"job": "stale_flag", **r}]}


@traced("purge_deleted")
def purge_deleted(s):
    r = freshness.purge_deleted(*_args(s))
    return {"results": [{"job": "purge_deleted", **r}]}


@traced("purge_threads")
def purge_threads(s):
    r = freshness.purge_threads(*_args(s))
    return {"results": [{"job": "purge_threads", **r}]}


@traced("summarize")
def summarize(s):
    _, days, dry = _args(s)
    return {"summary": freshness.combine(s.get("results") or [], days, dry)}
