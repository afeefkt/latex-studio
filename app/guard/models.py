# ── Phase 4: Guard models ──

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class MatchedRequirement(BaseModel):
    jd_phrase: str
    fact_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class TailorResponse(BaseModel):
    matched_requirements: list[MatchedRequirement]
    selected_bullet_ids: list[str]
    focus_phrase: str
    hook_key: str
    unmatched_requirements: list[str] = []
    notes_for_human: str = ""


class ValidationIssue(BaseModel):
    rule: int
    severity: Literal["error", "warning"]
    message: str
    detail: str = ""


class ValidationResult(BaseModel):
    passed: bool
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []


@dataclass
class FactBank:
    raw: dict
    all_fact_ids: set[str] = field(default_factory=set)
    all_numbers: set[str] = field(default_factory=set)
    all_entities: set[str] = field(default_factory=set)
    all_skills: set[str] = field(default_factory=set)
    banned_claims: list[str] = field(default_factory=list)
    certifications_held: list[str] = field(default_factory=list)
    certifications_in_progress: list[dict] = field(default_factory=list)
