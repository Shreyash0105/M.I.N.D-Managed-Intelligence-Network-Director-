"""Agent 4: Responder. Writes the answer and cites memories. It can never write to the database."""
import re
from app.core.config import settings
from app.core.util import age_str
from app.llm import provider as llm, prompts


def _clean(s: str) -> str:
    s = re.sub(r"</?memories>", "", s or "", flags=re.I)
    return s.replace('"', "'").replace("\n", " ")[:500]


def build_system(hits: list[dict]) -> str:
    """hits = public memory dicts (retrieval_service.public_view): JSON-safe, with a 1-based `ref`."""
    lines = []
    for i, h in enumerate(hits, 1):
        stale = " | STALE - confirm with user before relying on it" if h.get("status") == "stale" else ""
        lines.append(f'[m:{h.get("ref", i)}] {h["type"]} | {age_str(h.get("updated_at"))} | conf {(h.get("confidence") or 0.8):.2f}{stale} | "{_clean(h["content"])}"')
    return prompts.RESPONDER + "\n<memories>\n" + ("\n".join(lines) or "(none)") + "\n</memories>"


def stream(text: str, history: list[dict], hits: list[dict]):
    msgs = [*history, {"role": "user", "text": text}]
    yield from llm.stream(build_system(hits), msgs, settings.llm_model_main)


def parse_used(answer: str, hits: list[dict]) -> list[str]:
    """Memory ids the answer cited as [m:N] (N = the memory's `ref`)."""
    by_ref = {h.get("ref", i): h["id"] for i, h in enumerate(hits, 1)}
    used = []
    for n in re.findall(r"\[m:(\d+)\]", answer):
        mid = by_ref.get(int(n))
        if mid and mid not in used:
            used.append(mid)
    return used
