"""One file for the model. Everything else calls complete / complete_json / stream.
LLM_PROVIDER=fake gives canned, rule-based answers so tests and offline demos still work."""
import json
import logging
import re
import time

from app.core.config import settings

log = logging.getLogger("teammind.llm")
_client = None


def _gem():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.llm_api_key)
    return _client


def _cfg(system, temperature, max_tokens, json_mode=False, thinking=True):
    from google.genai import types
    kw = dict(system_instruction=system, temperature=temperature, max_output_tokens=max_tokens)
    if json_mode:
        kw["response_mime_type"] = "application/json"
    if thinking and settings.llm_thinking_budget >= 0:
        kw["thinking_config"] = types.ThinkingConfig(thinking_budget=settings.llm_thinking_budget)
    return types.GenerateContentConfig(**kw)


def _retry(fn, tries=2):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # rate limits etc.
            if i == tries - 1 or "INVALID_ARGUMENT" in str(e):  # a bad request never succeeds on retry
                raise
            log.warning("LLM call failed (%s), retrying", e)
            time.sleep(2)


def complete(system: str, user: str, model: str | None = None, max_tokens=900, temperature=0.2, json_mode=False) -> str:
    model = model or settings.llm_model_fast
    # (json_mode, thinking_config): the model may reject either option, so fall back step by step.
    # JSON is still parsed from plain text by _parse_json, so dropping json_mode is safe.
    variants = [(json_mode, True), (False, True), (False, False)] if json_mode else [(False, True), (False, False)]
    last = None
    for i, (jm, th) in enumerate(variants):
        try:
            r = _retry(lambda: _gem().models.generate_content(
                model=model, contents=user, config=_cfg(system, temperature, max_tokens, jm, th)))
            if i:
                log.warning("model %s only accepted json_mode=%s thinking=%s", model, jm, th)
            return r.text or ""
        except Exception as e:
            last = e
            if "INVALID_ARGUMENT" not in str(e):
                raise
            log.warning("model %s rejected json_mode=%s thinking=%s: %s", model, jm, th, str(e)[:150])
    raise last

def _parse_json(text: str):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def complete_json(system: str, user: str, model: str | None = None, task: str = "", fake: dict | None = None,
                  retries: int = 1, max_tokens=1200):
    """Returns parsed JSON or None. Callers must validate (Pydantic) and have a safe default."""
    if settings.llm_provider == "fake":
        return _fake_json(task, fake or {})
    for _ in range(retries + 1):
        try:
            out = _parse_json(complete(system + "\nReturn valid JSON only.", user, model, max_tokens=max_tokens,
                                       temperature=0, json_mode=True))
            if out is not None:
                return out
        except Exception as e:
            log.warning("complete_json(%s) failed: %s", task, e)
    return None


def stream(system: str, messages: list[dict], model: str | None = None):
    """messages: [{'role': 'user'|'assistant', 'text': str}]. Yields text pieces."""
    if settings.llm_provider == "fake":
        yield from _fake_stream(system, messages)
        return
    from google.genai import types
    msgs = list(messages)
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    contents = [types.Content(role="user" if m["role"] == "user" else "model",
                              parts=[types.Part(text=m["text"])]) for m in msgs]
    for chunk in _gem().models.generate_content_stream(
            model=model or settings.llm_model_main, contents=contents,
            config=_cfg(system, 0.4, 1200)):
        if chunk.text:
            yield chunk.text


# ---------------- fake provider (rule based) ----------------
_SMALL = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|cool|great|bye)\b[\s\W]*$", re.I)


def _fake_json(task, f):
    text = f.get("text", "")
    if task == "planner":
        words = [w for w in re.findall(r"[A-Za-z0-9_-]{4,}", text)][:6]
        return {"search_query": text, "keywords": words, "types": [], "need_memory": not _SMALL.match(text)}
    if task == "extractor":
        t = re.sub(r"(?i)^\s*remember\s*[:,-]?\s*", "", f.get("user", "")).strip()
        if not re.search(r"(?i)(remember|\bwe (use|chose|decided|switched|cannot|can't|must|need|moved|keep)|no budget|prefer|always|never|must|cannot)", f.get("user", "")):
            return []
        low = t.lower()
        typ = ("constraint" if re.search(r"cannot|can't|must|no budget|never|only", low)
               else "preference" if re.search(r"prefer|like|always", low)
               else "decision")
        tags = [w.lower() for w in re.findall(r"[A-Za-z]{5,}", t)[:3]]
        return [{"type": typ, "topic": " ".join(tags[:2]) or "general", "content": t.rstrip(".") + ".",
                 "tags": tags, "importance": 0.8, "confidence": 0.85, "worthiness": 0.8,
                 "expires_in_days": 7 if "this week" in low else None, "reason": "fake extractor"}]
    if task == "conflict":
        new, olds = f.get("new", ""), f.get("olds", [])
        nw = set(re.findall(r"\w+", new.lower()))
        for i, o in enumerate(olds, 1):
            ow = set(re.findall(r"\w+", o.lower()))
            overlap = len(nw & ow) / max(1, len(nw | ow))
            if re.search(r"(?i)\b(maybe|not sure|unsure|perhaps)\b", new) and overlap > 0.1:  # scripted "unsure" case
                return {"relation": "contradicts", "target": i, "reason": "unsure (fake)", "confidence": 0.4}
            if overlap > 0.85:
                return {"relation": "duplicate", "target": i, "reason": "same meaning", "confidence": 0.9}
            if re.search(r"(?i)switched|instead|no longer|actually|moved to|changed to|now use", new) and overlap > 0.1:
                return {"relation": "contradicts", "target": i, "reason": "newer decision replaces older", "confidence": 0.85}
        return {"relation": "unrelated", "target": None, "reason": "", "confidence": 0.8}
    if task == "stale":
        return {"stale": f.get("age_days", 0) >= settings.stale_days, "reason": "old time-sensitive memory (fake)"}
    if task == "reflection":
        items = f.get("items", [])
        return {"content": f"Lesson from {f.get('topic', 'this topic')}: " + "; ".join(i[:60] for i in items[:3]),
                "confidence": 0.65, "tags": ["lesson"]}
    return None


def _fake_stream(system, messages):
    mems = re.findall(r'\[m:(\d+)\][^"\n]*"(.*)"', system)
    if mems:
        text = "Based on what the team remembers: " + " ".join(f"{c} [m:{n}]" for n, c in mems[:3])
    else:
        text = "I don't have any stored team context about that yet. (fake LLM mode)"
    for w in text.split(" "):
        yield w + " "
