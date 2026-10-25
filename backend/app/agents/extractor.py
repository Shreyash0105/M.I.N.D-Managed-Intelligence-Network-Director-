"""Agent 5: Extractor. Decides what is worth remembering."""
from app.core.config import settings
from app.db.schemas import Candidate
from app.llm import provider as llm, prompts


def extract(user_text: str, answer_text: str = "", min_worthiness: float | None = None) -> list[Candidate]:
    th = settings.worthiness_threshold if min_worthiness is None else min_worthiness
    raw = llm.complete_json(prompts.EXTRACTOR, f"USER: {user_text}\nASSISTANT: {answer_text[:1500]}",
                            settings.llm_model_fast, task="extractor", fake={"user": user_text}, max_tokens=1500)
    if isinstance(raw, dict):
        raw = raw.get("memories") or raw.get("items") or [raw]
    out = []
    for item in raw or []:
        try:
            c = Candidate(**item)
        except Exception:
            continue
        if c.worthiness >= th and c.content.strip():
            out.append(c)
    return out
