"""Small helpers shared by all nodes: per-node timing for the Run trace, and a safe stream writer."""
import functools
import time

from langgraph.config import get_stream_writer
from langgraph.types import Command


def writer():
    """Custom stream writer; a no-op when the graph is not being streamed (tests, MCP, background runs)."""
    try:
        return get_stream_writer()
    except Exception:
        return lambda _event: None


def traced(name: str, model: str = ""):
    """Wrap a node so its trace entry always has node name + milliseconds (+ model for LLM nodes).
    The node may return its own trace entry with extra fields; timing is merged into it."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state, *a, **k):
            t = time.time()
            out = fn(state, *a, **k)
            ms = int((time.time() - t) * 1000)
            upd = out.update if isinstance(out, Command) else out
            if isinstance(upd, dict):
                entries = list(upd.get("trace") or [])
                mine = next((e for e in entries if isinstance(e, dict) and e.get("node") == name), None)
                if mine is None:
                    mine = {"node": name}
                    entries.append(mine)
                mine.setdefault("ms", ms)
                if model:
                    mine.setdefault("model", model)
                upd["trace"] = entries
            elif isinstance(out, Command) and upd is None:
                out = Command(update={"trace": [{"node": name, "ms": ms}]}, goto=out.goto)
            return out
        return wrapper
    return deco
