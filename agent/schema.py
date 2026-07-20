"""
schema.py

Pydantic models that define the structured formats used throughout the agent.
Using Pydantic here matters for two reasons:
  1. It gives us a hard contract for what "valid" parsed output looks like -
     if Qwen3 returns something that doesn't fit, we catch it immediately
     instead of letting garbage flow into search/filter/validate.
  2. It's exactly what the assignment asks for in section 4.1 ("structured
     format containing...").
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class HardConstraints(BaseModel):
    """Constraints that MUST be satisfied. Never silently ignored downstream."""
    locations: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    minimum_capacity: Optional[int] = None
    maximum_delivery_days: Optional[int] = None
    budget: Optional[int] = None
    require_immediate_availability: bool = False


class StructuredRequirement(BaseModel):
    """The parsed form of a user's free-text business request."""
    objective: str
    entity_type: Literal["supplier", "professional", "opportunity"]
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    requested_results: int = 3
    raw_request: str = ""
    reconciliation_notes: List[str] = Field(default_factory=list)


class RecommendationCandidate(BaseModel):
    """One ranked recommendation, produced after scoring, before validation."""
    id: str
    name: Optional[str] = None
    match_score: float
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)
