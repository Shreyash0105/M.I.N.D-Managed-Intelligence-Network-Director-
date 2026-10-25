"""Agent 3: Retriever. Hybrid search (Atlas $vectorSearch + $search) -> RRF -> re-rank -> explain.
Falls back to a local scan when Atlas indexes are missing/not ready, and reports which mode was used."""
import logging
import math
import re

import numpy as np

from app.core.config import settings
from app.core.util import age_str, utcnow
from app.db.mongo import db
from app.llm import provider as llm, prompts
from app.services import events_service as ev
from app.services.embeddings import embed
from app.services.memory_service import visible_filter

log = logging.getLogger("teammind.retrieval")
ACTIVE = ["active", "stale"]
status_info = {"mode": "unknown", "errors": []}


def vector_search(qvec, ws, uid, types=None, limit=20):
    flt = {"workspace_id": ws, "status": {"$in": ACTIVE},
           "$or": [{"scope": {"$in": ["workspace", "shared"]}}, {"user_id": uid}]}
    if types:
        flt["type"] = {"$in": types}
    return list(db.memories.aggregate([
        {"$vectorSearch": {"index": "memory_vector", "path": "embedding", "queryVector": qvec,
                           "numCandidates": 150, "limit": limit, "filter": flt}},
        {"$addFields": {"_atlas_sem": {"$meta": "vectorSearchScore"}}}]))


def keyword_search(keywords, ws, uid, types=None, limit=20):
    kws = [k for k in keywords if k]
    if not kws:
        return []
    return list(db.memories.aggregate([
        {"$search": {"index": "memory_text", "compound": {
            "must": [{"text": {"query": " ".join(kws), "path": ["content", "topic", "tags"]}}],
            "filter": [{"equals": {"path": "workspace_id", "value": ws}},
                       {"compound": {"should": [{"equals": {"path": "status", "value": s}} for s in ACTIVE],
                                     "minimumShouldMatch": 1}}]}}},
        {"$limit": limit},
        {"$addFields": {"_kw": {"$meta": "searchScore"}}}]))


def local_scan(qvec, keywords, ws, uid, limit=20, cap=3000):
    """Fallback: cosine over stored embeddings + simple keyword overlap. Works with any MongoDB."""
    docs = list(db.memories.find({**visible_filter(ws, uid), "status": {"$in": ACTIVE}}).limit(cap))
    q = np.array(qvec)
    kws = [k.lower() for k in keywords if k]
    vec = []
    for d in docs:
        d["_atlas_sem"] = float(np.dot(q, np.array(d["embedding"]))) if d.get("embedding") else 0.0
        hay = f"{d.get('content', '')} {d.get('topic', '')} {' '.join(d.get('tags', []))}".lower()
        d["_kw"] = sum(1 for k in kws if k in hay) / max(1, len(kws)) if kws else 0.0
        vec.append(d)
    by_sem = sorted(vec, key=lambda x: x["_atlas_sem"], reverse=True)[:limit]
    by_kw = sorted([d for d in vec if d["_kw"] > 0], key=lambda x: x["_kw"], reverse=True)[:limit]
    return by_sem, by_kw


def rrf(lists, k=60):
    score, doc = {}, {}
    for lst in lists:
        for rank, d in enumerate(lst):
            score[d["_id"]] = score.get(d["_id"], 0) + 1 / (k + rank + 1)
            doc[d["_id"]] = {**doc.get(d["_id"], {}), **d}
    return [doc[i] | {"_rrf": score[i]} for i in sorted(score, key=score.get, reverse=True)]


def _matched(d, keywords):
    hay = f"{d.get('content', '')} {d.get('topic', '')} {' '.join(d.get('tags', []))}".lower()
    return [k for k in keywords if k and k.lower() in hay]


def _rerank(query, hits):
    """Optional LLM reranker (smarter memory). Blends 30% LLM relevance into the final score."""
    top = hits[:8]
    listing = "\n".join(f"{i}. {h['content'][:200]}" for i, h in enumerate(top, 1))
    out = llm.complete_json(prompts.RERANK, f"Query: {query}\nMemories:\n{listing}", settings.llm_model_fast,
                            task="rerank", max_tokens=500)
    if not isinstance(out, list):
        return hits
    for r in out:
        try:
            h = top[int(r["n"]) - 1]
            h["_llm"] = max(0.0, min(1.0, float(r["score"])))
            h["_final"] = 0.7 * h["_final"] + 0.3 * h["_llm"]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    return sorted(hits, key=lambda h: h["_final"], reverse=True)


def search(plan: dict, ws: str, uid: str, k: int = 5, track: bool = True, types_filter=None):
    """Returns (hits, info). info = {mode, errors}."""
    query = plan["search_query"]
    keywords = plan.get("keywords") or re.findall(r"\w{4,}", query)
    qvec = embed(query)
    vec, kw, errors, ok = [], [], [], []
    try:
        vec = vector_search(qvec, ws, uid, types_filter); ok.append("vector")
    except Exception as e:
        errors.append(f"vector: {e}")
    try:
        kw = keyword_search(keywords, ws, uid, types_filter); ok.append("keyword")
    except Exception as e:
        errors.append(f"keyword: {e}")
    if errors or not (vec or kw):
        lv, lk = local_scan(qvec, keywords, ws, uid)
        if lv or lk:
            if not vec and not kw:
                vec, kw = lv, lk
                ok = ["local-fallback"]
            if errors:
                log.warning("Atlas search problem, using local fallback: %s", errors)
    mode = "hybrid" if set(ok) == {"vector", "keyword"} else ("vector-only" if ok == ["vector"] else
           "keyword-only" if ok == ["keyword"] else (ok[0] if ok else "none"))
    status_info.update(mode=mode, errors=errors)

    now = utcnow()
    merged = rrf([vec, kw])
    max_kw = max([d.get("_kw", 0) for d in merged] + [1e-9])
    out = []
    for d in merged:
        if d.get("workspace_id") != ws:
            continue  # defense in depth
        if d.get("scope") == "private" and d.get("user_id") != uid:
            continue
        if d.get("status") not in ACTIVE or "injection" in d.get("flags", []):
            continue
        if types_filter and d.get("type") not in types_filter:
            continue
        if (d.get("expires_at") and d["expires_at"] <= now) or (d.get("valid_until") and d["valid_until"] <= now):
            continue  # read-time expiry (TTL deletes later)
        emb = d.pop("embedding", None)
        sem = float(np.dot(qvec, emb)) if emb else float(d.get("_atlas_sem", 0))
        matched = _matched(d, keywords)
        if sem < settings.min_semantic and not matched:
            continue
        age_days = max(0, (now - d["updated_at"]).total_seconds() / 86400)
        recency = 0.5 ** (age_days / 30)
        kwn = d.get("_kw", 0) / max_kw if d.get("_kw") else (0.5 if matched else 0)
        final = (settings.w_semantic * max(sem, 0) + settings.w_keyword * kwn + settings.w_recency * recency
                 + settings.w_importance * d.get("importance", 0.5))
        if d.get("type") in plan.get("types", []):
            final += 0.04
        d.update(_sem=sem, _kwn=kwn, _rec=recency, _final=final, _matched=matched)
        out.append(d)
    out.sort(key=lambda x: x["_final"], reverse=True)
    if settings.rerank_enabled and len(out) > 1:
        out = _rerank(query, out)
    out = out[:k]
    for d in out:
        bits = [f"meaning match {d['_sem']:.2f}"]
        if d["_matched"]:
            bits.append("keyword: " + ", ".join(d["_matched"][:3]))
        bits += [f"updated {age_str(d['updated_at'])}", f"importance {d.get('importance', 0.5):.1f}"]
        if "_llm" in d:
            bits.append(f"reranker {d['_llm']:.2f}")
        d["_why"] = " · ".join(bits)
    if track and out:
        ids = [d["_id"] for d in out]
        db.memories.update_many({"_id": {"$in": ids}}, {"$inc": {"access_count": 1}, "$set": {"last_accessed_at": now}})
        db.memory_events.insert_many([{"workspace_id": ws, "memory_id": str(i), "action": "used", "actor": uid,
                                       "reason": query[:120], "extra": {}, "ts": now} for i in ids])
    return out, {"mode": mode, "errors": errors}


def similar(text_vec, ws, uid, limit=5):
    """For the Conflict Resolver: close active memories (true cosine >= threshold)."""
    try:
        docs = vector_search(text_vec, ws, uid, None, limit=limit)
        if not docs:
            raise RuntimeError("empty")
    except Exception:
        docs, _ = local_scan(text_vec, [], ws, uid, limit=limit)
    out = []
    for d in docs:
        emb = d.pop("embedding", None)
        d["_sem"] = float(np.dot(text_vec, emb)) if emb else float(d.get("_atlas_sem", 0))
        if d["_sem"] >= settings.similarity_threshold and d.get("status") in ACTIVE:
            out.append(d)
    return sorted(out, key=lambda x: x["_sem"], reverse=True)


def public_view(hits):
    out = []
    for i, h in enumerate(hits, 1):
        out.append({
            "ref": i, "id": str(h["_id"]), "type": h["type"], "topic": h.get("topic"), "content": h["content"],
            "status": h["status"], "scope": h.get("scope"), "confidence": h.get("confidence"),
            "importance": h.get("importance"), "tags": h.get("tags", []),
            "updated_at": h["updated_at"].isoformat(), "expires_at": h["expires_at"].isoformat() if h.get("expires_at") else None,
            "scores": {"semantic": round(h["_sem"], 3), "keyword": round(h["_kwn"], 3),
                       "recency": round(h["_rec"], 3), "importance": round(h.get("importance", 0.5), 3),
                       "final": round(h["_final"], 3), **({"reranker": round(h["_llm"], 3)} if "_llm" in h else {})},
            "why": h["_why"]})
    return out
