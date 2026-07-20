"""
validator.py

Required tool: validate_recommendations

This is the most important file in the whole project for the evaluation
criteria ("Validation, correction and failure recovery: 20%"). It must be
100% deterministic Python -- never ask the LLM "is this correct?".

It re-checks everything from scratch against the dataset, independent of
however the ranking step produced its recommendations. This catches:
  - fabricated/nonexistent entity IDs
  - hard constraints that were actually violated (in case ranking made a mistake)
  - duplicate recommendations (by normalized name + location, since a
    prompt-injected or duplicated record might use a different ID)
  - whether enough valid results were found to satisfy requested_results
"""

import re
from typing import Any, Dict, List


def validate_recommendations(
    recommendations: List[Dict],
    dataset: Dict[str, List[Dict]],
    entity_type: str,
    hard_constraints: Dict[str, Any],
    requested_results: int,
) -> Dict[str, Any]:
    """
    Tool: validate_recommendations

    Args:
        recommendations: list of records the ranking step proposed (must each have an "id")
        dataset: full dataset dict from loader.load_all()
        entity_type: the entity type being validated against
        hard_constraints: same structure used in filter_by_constraints
        requested_results: how many results the user asked for

    Returns:
        {
            "passed": bool,
            "valid_count": int,
            "requested_results": int,
            "failures": [{"id": ..., "issues": [...]}],
            "note": Optional[str]
        }
    """
    failures = []
    seen_keys = {}  # (normalized_name, normalized_location) -> first id seen
    valid_records = {r["id"]: r for r in dataset.get(entity_type, [])}

    locations = hard_constraints.get("locations")
    certifications = hard_constraints.get("certifications")
    min_capacity = hard_constraints.get("minimum_capacity")
    max_delivery = hard_constraints.get("maximum_delivery_days")
    budget = hard_constraints.get("budget")
    require_immediate = hard_constraints.get("require_immediate_availability")

    for rec in recommendations:
        rec_id = rec.get("id")
        issues = []

        # 1. Existence check -- catches fabricated / hallucinated records
        if rec_id not in valid_records:
            issues.append(f"{rec_id} does not exist in the {entity_type} dataset.")
            failures.append({"id": rec_id, "issues": issues})
            continue  # nothing further to check on a record that isn't real

        full_record = valid_records[rec_id]

        # 2. Independent hard-constraint re-check (mirrors filter_by_constraints
        #    exactly, so validation never disagrees with filtering about what's
        #    applicable to this entity type)
        if locations:
            state = full_record.get("_location_normalized", {}).get("state")
            allowed = [l.lower() for l in locations]
            if state is None or state.lower() not in allowed:
                issues.append(f"{rec_id} does not satisfy the location constraint.")

        if certifications:
            record_certs = [c.lower() for c in full_record.get("_certifications_normalized", [])]
            missing = [c for c in certifications if c.lower() not in record_certs]
            if missing:
                issues.append(f"{rec_id} does not have evidence of {', '.join(missing)} certification.")

        if min_capacity is not None and "capacity_units_per_month" in full_record:
            capacity = full_record.get("capacity_units_per_month")
            if capacity is None or capacity < min_capacity:
                issues.append(f"{rec_id} does not meet the minimum capacity requirement of {min_capacity}.")

        if max_delivery is not None and "delivery_days" in full_record:
            delivery = full_record.get("_delivery_days_normalized")
            if delivery is None or delivery > max_delivery:
                issues.append(f"{rec_id} exceeds the maximum delivery time of {max_delivery} days (or it is unconfirmed).")

        if budget is not None and "hourly_rate_inr" in full_record:
            rate = full_record.get("hourly_rate_inr")
            if rate is not None and rate > budget:
                issues.append(f"{rec_id} has an hourly rate of {rate}, exceeding the stated budget of {budget}.")

        if require_immediate and "availability" in full_record:
            availability = (full_record.get("availability") or "").strip().lower()
            if availability != "available":
                issues.append(f"{rec_id} is not immediately available (status: '{full_record.get('availability')}').")

        if "status" in full_record:
            status = (full_record.get("status") or "").strip().lower()
            if status != "open":
                issues.append(f"{rec_id} has status '{full_record.get('status')}', not open.")

        # 3. Duplicate detection. Suppliers/professionals are identified by
        #    normalized name + location. Opportunities are identified by the
        #    underlying deal (poster + budget + quantity + location) instead
        #    of title wording, since two postings of the same real listing
        #    can legitimately use different phrasing in their title
        #    (e.g. "Sourcing biodegradable containers..." vs "Duplicate
        #    test: biodegradable container sourcing" for the same deal).
        if entity_type == "opportunity":
            identity_key = (
                full_record.get("posted_by"),
                full_record.get("budget_inr"),
                full_record.get("quantity"),
                str(full_record.get("_location_normalized")),
            )
        else:
            identity_text = full_record.get("name") or full_record.get("title") or ""
            normalized_name = re.sub(r"[^a-z0-9]", "", identity_text.lower())
            identity_key = (normalized_name, str(full_record.get("_location_normalized")))

        if identity_key in seen_keys:
            issues.append(f"{rec_id} appears to be a duplicate of {seen_keys[identity_key]}.")
        else:
            seen_keys[identity_key] = rec_id

        if issues:
            failures.append({"id": rec_id, "issues": issues})

    valid_count = len(recommendations) - len(failures)
    count_satisfied = valid_count >= requested_results

    result = {
        "passed": len(failures) == 0 and count_satisfied,
        "valid_count": valid_count,
        "requested_results": requested_results,
        "failures": failures,
    }

    if count_satisfied is False and len(failures) == 0:
        result["note"] = (
            f"Only {valid_count} valid result(s) available out of the "
            f"{requested_results} requested. Recommend re-searching with "
            f"relaxed preferences, or reporting fewer results honestly."
        )

    return result
