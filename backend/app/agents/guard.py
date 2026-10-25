"""Agent 1: Guard. Rules first (fast, predictable). Secrets are blocked, personal data redacted/private."""
import re

RULES = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("api_key", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{35})")),
    ("mongo_uri", re.compile(r"mongodb(\+srv)?://[^\s:@]+:[^\s@]+@\S+")),
    ("password", re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+")),
]
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PERSONAL = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("phone", re.compile(r"\+?\d[\d\s-]{9,}\d")),
]
SECRET = {"private_key", "api_key", "mongo_uri", "password", "card"}

INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+|the\s+)?(previous\s+|prior\s+|above\s+|earlier\s+)?(instructions|rules|prompts?)"
    r"|disregard\s+(all\s+|the\s+)?(previous|prior|system|above)"
    r"|(reveal|show|print|repeat)\s+(me\s+)?(the\s+|your\s+)?(system\s+)?prompt"
    r"|new\s+instructions\s*:"
    r"|forget\s+(all\s+)?(your|previous)\s+(rules|instructions)"
    r"|</?memories>)")


def _luhn(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan_injection(text: str) -> bool:
    """True if text looks like it is trying to give the AI new orders."""
    return bool(INJECTION.search(text or ""))


def check(text: str) -> dict:
    findings, clean = [], text or ""
    for name, rx in RULES:
        if rx.search(clean):
            findings.append(name)
            clean = rx.sub(f"[REDACTED:{name}]", clean)
    hit = []

    def card_sub(m):
        if _luhn(m.group()):
            hit.append(1)
            return "[REDACTED:card]"
        return m.group()

    clean = CARD.sub(card_sub, clean)
    if hit:
        findings.append("card")
    for name, rx in PERSONAL:
        if rx.search(clean):
            findings.append(name)
            clean = rx.sub(f"[REDACTED:{name}]", clean)
    if any(f in SECRET for f in findings):
        action = "block"
    elif findings:
        action = "save_private"
    else:
        action = "allow"
    return {"action": action, "findings": findings, "clean_text": clean}
