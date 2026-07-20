"""
scoring.py

Optional tool: calculate_match_score

Implements the weighted scoring method from section 6 of the assignment:
  - Product/skill relevance:        30%
  - Location suitability:           20%
  - Hard-constraint compliance:     25%
  - Availability or capacity:       15%
  - Reputation / past performance:  10%

Every component is computed from a specific dataset field so the score is
always traceable back to evidence - never an arbitrary number the LLM made up.
This file has NO LLM involvement at all.
"""

from typing import Any, Dict, List, Optional

WEIGHTS = {
    "relevance": 0.30,
    "location": 0.20,
    "hard_constraint_compliance": 0.25,
    "availability_capacity": 0.15,
    "reputation": 0.10,
}


def _relevance_score(record: Dict, hard_constraints: Dict[str, Any]) -> float:
    """
    Records reaching this point already matched the requested category during
    search, so base relevance is 1.0. We don't invent finer-grained relevance
    without more evidence than a keyword match provides.
    """
    return 1.0


def _location_score(record: Dict, hard_constraints: Dict[str, Any]) -> float:
    locations = hard_constraints.get("locations")
    if not locations:
        return 1.0  # no location constraint was stated, so it's not a differentiator
    state = record.get("_location_normalized", {}).get("state")
    if state and state.lower() in [l.lower() for l in locations]:
        return 1.0
    return 0.0  # should not normally occur post-filter; scored honestly if it does


def _hard_constraint_compliance_score(record: Dict, hard_constraints: Dict[str, Any]) -> float:
    """
    Rather than a flat 1.0/0.0, this measures HOW COMFORTABLY the record clears
    each stated constraint (e.g. capacity margin, delivery-time margin, budget
    margin), so two records that both technically pass can still be ranked apart.
    """
    sub_scores = []

    min_capacity = hard_constraints.get("minimum_capacity")
    if min_capacity and "capacity_units_per_month" in record:
        capacity = record.get("capacity_units_per_month") or 0
        # 1.0 once capacity is double the minimum requirement or more
        sub_scores.append(min(capacity / (min_capacity * 2), 1.0))

    max_delivery = hard_constraints.get("maximum_delivery_days")
    if max_delivery and "delivery_days" in record:
        delivery = record.get("_delivery_days_normalized")
        if delivery is not None:
            margin = (max_delivery - delivery) / max_delivery
            sub_scores.append(max(0.0, min(margin + 0.5, 1.0)))  # partial credit even at the deadline

    certifications = hard_constraints.get("certifications")
    if certifications:
        record_certs = [c.lower() for c in record.get("_certifications_normalized", [])]
        matched = sum(1 for c in certifications if c.lower() in record_certs)
        sub_scores.append(matched / len(certifications))

    budget = hard_constraints.get("budget")
    if budget and "hourly_rate_inr" in record:
        rate = record.get("hourly_rate_inr")
        if rate is not None and budget > 0:
            # more room under budget = higher score; at-budget still earns partial credit
            margin = (budget - rate) / budget
            sub_scores.append(max(0.0, min(margin + 0.5, 1.0)))

    if hard_constraints.get("require_immediate_availability") and "availability" in record:
        availability = (record.get("availability") or "").strip().lower()
        sub_scores.append(1.0 if availability == "available" else 0.0)

    if not sub_scores:
        return 1.0  # no hard constraints stated to measure margin against
    return sum(sub_scores) / len(sub_scores)


def _availability_capacity_score(record: Dict, max_capacity_in_group: Optional[int]) -> float:
    """
    For suppliers: capacity relative to the strongest candidate in the group.
    For professionals (no monthly capacity field): experience_years is used as
    a proxy for depth of available capacity, so this component still
    differentiates candidates instead of defaulting to a flat neutral score.
    """
    if "capacity_units_per_month" in record:
        capacity = record.get("capacity_units_per_month")
        if capacity is None or not max_capacity_in_group:
            return 0.5
        return min(capacity / max_capacity_in_group, 1.0)

    if "experience_years" in record:
        experience = record.get("experience_years") or 0
        return min(experience / 15, 1.0)  # 15+ years treated as full depth

    return 0.5  # unknown entity shape - neutral, not penalized or rewarded


def _reputation_score(record: Dict) -> float:
    rating = record.get("rating")
    past_interactions = record.get("past_interactions", 0)
    if rating is None:
        return 0.3  # no rating on file - scored low but not zero
    rating_component = rating / 5.0
    confidence_component = min(past_interactions / 20, 1.0)
    return rating_component * 0.7 + confidence_component * 0.3


def calculate_match_score(
    record: Dict,
    hard_constraints: Dict[str, Any],
    max_capacity_in_group: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tool: calculate_match_score
    Returns the total weighted score (0-1) plus a full breakdown so every
    number can be explained back to the user.
    """
    breakdown = {
        "relevance": round(_relevance_score(record, hard_constraints), 3),
        "location": round(_location_score(record, hard_constraints), 3),
        "hard_constraint_compliance": round(_hard_constraint_compliance_score(record, hard_constraints), 3),
        "availability_capacity": round(_availability_capacity_score(record, max_capacity_in_group), 3),
        "reputation": round(_reputation_score(record), 3),
    }
    total = sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS)

    return {
        "id": record.get("id"),
        "name": record.get("name") or record.get("title"),
        "match_score": round(total, 3),
        "score_breakdown": {k: {"value": breakdown[k], "weight": WEIGHTS[k]} for k in WEIGHTS},
    }


def rank_candidates(records: List[Dict], hard_constraints: Dict[str, Any]) -> List[Dict]:
    """Score every candidate and return them sorted best-first."""
    max_capacity = max(
        (r.get("capacity_units_per_month") or 0 for r in records), default=0
    ) or None

    scored = [calculate_match_score(r, hard_constraints, max_capacity) for r in records]
    scored.sort(key=lambda s: s["match_score"], reverse=True)
    return scored
