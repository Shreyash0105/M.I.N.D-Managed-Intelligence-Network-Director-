from typing import Literal, Optional, List
from pydantic import BaseModel, field_validator

MEM_TYPES = ["preference", "decision", "constraint", "feedback", "outcome", "strategy", "fact", "episode"]
MemType = Literal["preference", "decision", "constraint", "feedback", "outcome", "strategy", "fact", "episode"]
Scope = Literal["private", "workspace", "shared"]


def _clamp(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


class Candidate(BaseModel):
    type: MemType = "fact"
    topic: str = "general"
    content: str
    tags: List[str] = []
    importance: float = 0.6
    confidence: float = 0.8
    worthiness: float = 0.8
    expires_in_days: Optional[float] = None
    reason: str = ""
    scope: Scope = "workspace"
    agent_id: Optional[str] = None
    source: Optional[dict] = None

    @field_validator("importance", "confidence", "worthiness", mode="before")
    @classmethod
    def _c(cls, v):
        return _clamp(v)

    @field_validator("tags", mode="before")
    @classmethod
    def _t(cls, v):
        return [str(x).lower() for x in v] if isinstance(v, list) else []

    @field_validator("type", mode="before")
    @classmethod
    def _ty(cls, v):
        v = str(v or "fact").lower()
        return v if v in MEM_TYPES else "fact"

    @field_validator("topic", mode="before")
    @classmethod
    def _tp(cls, v):
        return str(v).strip()[:80] if v else "general"

    @field_validator("expires_in_days", mode="before")
    @classmethod
    def _e(cls, v):
        try:
            return float(v) if v not in (None, "", 0) else None
        except (TypeError, ValueError):
            return None


class Verdict(BaseModel):
    relation: Literal["duplicate", "refines", "contradicts", "unrelated"] = "unrelated"
    target: Optional[int] = None
    reason: str = ""
    merged_content: Optional[str] = None
    confidence: float = 0.7

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        return _clamp(v)


class PlanOut(BaseModel):
    search_query: str
    keywords: List[str] = []
    types: List[str] = []
    need_memory: bool = True


# ---- API request bodies ----
class RegisterIn(BaseModel):
    name: str
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class WorkspaceIn(BaseModel):
    name: str


class InviteIn(BaseModel):
    email: str
    role: Literal["member", "viewer"] = "member"


class TokenIn(BaseModel):
    label: str = "agent"
    scope: Literal["read", "readwrite"] = "readwrite"


class ChatIn(BaseModel):
    text: str
    conversation_id: Optional[str] = None
    memory_on: bool = True
    ephemeral: bool = False


class MemoryIn(BaseModel):
    content: str
    type: MemType = "fact"
    topic: str = "general"
    tags: List[str] = []
    scope: Scope = "workspace"
    importance: float = 0.6
    expires_in_days: Optional[float] = None


class MemoryPatch(BaseModel):
    content: Optional[str] = None
    reason: str = "manual correction"
    pinned: Optional[bool] = None


class ImportIn(BaseModel):
    text: str


class CommitIn(BaseModel):
    items: List[Candidate]


class JobIn(BaseModel):
    days_ahead: int = 0
    dry_run: bool = False
    require_approval: Optional[bool] = None  # Reflection: ask a human before saving a lesson


class ResumeIn(BaseModel):
    choice: str  # conflict: use_new | keep_old | keep_both   lesson: approve | reject


class DemoModeIn(BaseModel):
    ask_on_conflict: bool
