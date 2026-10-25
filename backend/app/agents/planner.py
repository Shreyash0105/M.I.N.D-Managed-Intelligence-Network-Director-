"""Agent 2: Query Planner. Rewrites the message into a search query. Never answers it."""
import re
from app.core.config import settings
from app.db.schemas import PlanOut, MEM_TYPES
from app.llm import provider as llm, prompts

SMALL = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|cool|great|bye)\b[\s\W]*$", re.I)


def _kw(text):
    return list(dict.fromkeys(re.findall(r"[A-Za-z0-9_-]{4,}", text)))[:6]


def plan(text: str, history: list[dict]) -> dict:
    default = {"search_query": text, "keywords": _kw(text), "types": [], "need_memory": True}
    if SMALL.match(text):
        return {**default, "need_memory": False}
    hist = "\n".join(f"{m['role']}: {m['text'][:300]}" for m in history[-6:])
    out = llm.complete_json(prompts.PLANNER, f"Recent turns:\n{hist or '(none)'}\n\nLatest user message: {text}",
                            settings.llm_model_fast, task="planner", fake={"text": text}, max_tokens=400)
    try:
        p = PlanOut(**out).model_dump()
        p["types"] = [t for t in p["types"] if t in MEM_TYPES]
        p["keywords"] = p["keywords"] or _kw(text)
        return p
    except Exception:
        return default
