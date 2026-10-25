"""Agent 6: Conflict Resolver. Guard -> injection scan -> find similar -> judge -> save/reinforce/supersede."""
from app.agents import guard
from app.core.config import settings
from app.db.schemas import Candidate, Verdict
from app.llm import provider as llm, prompts
from app.services import memory_service as memory, retrieval_service as retrieval
from app.services.embeddings import embed, memory_text


def brief(d):
    return {"id": str(d["_id"]), "type": d["type"], "topic": d.get("topic"), "content": d["content"]}


def judge(cand: Candidate, similar: list[dict]) -> Verdict:
    olds = [s["content"] for s in similar]
    listing = "\n".join(f"{i}. {o}" for i, o in enumerate(olds, 1))
    raw = llm.complete_json(prompts.CONFLICT, f"NEW: {cand.content}\nOLD:\n{listing}", settings.llm_model_fast,
                            task="conflict", fake={"new": cand.content, "olds": olds}, max_tokens=500)
    try:
        return Verdict(**raw)
    except Exception:
        return Verdict(relation="unrelated", confidence=0.5)  # safe default: just save it


def store_candidate(ws: str, uid: str, cand: Candidate, actor: str = "agent") -> dict:
    g = guard.check(cand.content)
    if g["action"] == "block":
        return {"status": "blocked", "findings": g["findings"],
                "message": f"Not saved: it looks like a secret ({', '.join(g['findings'])})."}
    data = cand.model_dump()
    data["content"] = g["clean_text"]
    if g["action"] == "save_private":
        data["scope"] = "private"
    data["agent_id"] = data.get("agent_id") or (actor if actor.startswith("agent:") else None)
    note = f" (hid {', '.join(g['findings'])})" if g["findings"] else ""

    def made(doc, status, msg, old_id=None):
        r = {"status": status, "id": str(doc["_id"]), "memory": brief(doc), "message": msg + note}
        if old_id:
            r["old_id"] = str(old_id)
        if "injection" in doc.get("flags", []):
            r.update(status="saved_flagged", message="Saved but flagged as a possible prompt injection; it will never be shown to the AI.")
        return r

    similar = retrieval.similar(embed(memory_text(data)), ws, uid, limit=5)
    if not similar:
        doc = memory.create_memory(ws, uid, data, actor)
        return made(doc, "saved", f"Remembered: {data['type']} - {data['topic']}")

    v = judge(cand, similar)
    target = similar[v.target - 1] if v.target and 1 <= v.target <= len(similar) else None
    if v.relation == "unrelated" or not target:
        doc = memory.create_memory(ws, uid, data, actor)
        return made(doc, "saved", f"Remembered: {data['type']} - {data['topic']}")
    if v.confidence < 0.6:
        data["flags"] = ["needs_review"]
        doc = memory.create_memory(ws, uid, data, actor, reason="unsure about conflict")
        return made(doc, "saved_review", "Saved, but it may conflict with an older memory. Please review.")
    if v.relation == "duplicate":
        memory.reinforce(ws, target["_id"])
        return {"status": "reinforced", "id": str(target["_id"]), "memory": brief(target),
                "message": "Already known. Reinforced the existing memory."}
    if v.relation == "refines" and v.merged_content:
        data["content"] = v.merged_content
    new = memory.supersede(ws, uid, target["_id"], data, actor, v.reason or v.relation)
    return made(new, "superseded", f"You said \"{target['content'][:60]}\" before; now updated.", old_id=target["_id"])
