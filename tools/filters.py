"""
filters.py

Required tool: filter_by_constraints

This is where hard constraints are enforced. Every rejected record gets a
plain-English reason, because the assignment requires:
  - "Hard constraints must never be silently ignored"
  - the final output to list "missing information" and "constraints checked"
"""

from typing import Any, Dict, List


def filter_by_constraints(records: List[Dict], hard_constraints: Dict[str, Any]) -> Dict[str, List]:
    """
    Tool: filter_by_constraints
    Removes any record that fails a hard constraint.

    Args:
        records: candidate records, typically the output of search_entities
        hard_constraints: dict possibly containing:
            - locations: List[str]
            - certifications: List[str]
            - minimum_capacity: int
            - maximum_delivery_days: int

    Returns:
        {
            "passed": [...records that satisfied every hard constraint...],
            "rejected": [{"id", "name", "reasons": [...]}, ...]
        }
    """
    passed = []
    rejected = []

    locations = hard_constraints.get("locations")
    certifications = hard_constraints.get("certifications")
    min_capacity = hard_constraints.get("minimum_capacity")
    max_delivery = hard_constraints.get("maximum_delivery_days")
    budget = hard_constraints.get("budget")
    require_immediate = hard_constraints.get("require_immediate_availability")

    for r in records:
        reasons = []

        if locations:
            state = r.get("_location_normalized", {}).get("state")
            allowed = [l.lower() for l in locations]
            if state is None:
                reasons.append("Location missing or ambiguous; cannot confirm location requirement is met.")
            elif state.lower() not in allowed:
                reasons.append(f"Location '{state}' is not in the allowed list {locations}.")

        if certifications:
            record_certs = [c.lower() for c in r.get("_certifications_normalized", [])]
            missing = [c for c in certifications if c.lower() not in record_certs]
            if missing:
                reasons.append(f"Missing required certification(s): {missing}.")

        # Capacity/delivery only apply to entity types that actually carry
        # those fields (suppliers). Applying them to professionals - who have
        # no capacity_units_per_month or delivery_days at all - would reject
        # every professional record on a field that isn't part of their schema.
        if min_capacity is not None and "capacity_units_per_month" in r:
            capacity = r.get("capacity_units_per_month")
            if capacity is None:
                reasons.append("Capacity not specified in record.")
            elif capacity < min_capacity:
                reasons.append(f"Capacity {capacity} is below the required minimum {min_capacity}.")

        if max_delivery is not None and "delivery_days" in r:
            delivery = r.get("_delivery_days_normalized")
            if delivery is None:
                reasons.append("Delivery time unconfirmed in record (e.g. listed as 'TBD').")
            elif delivery > max_delivery:
                reasons.append(f"Delivery time {delivery} days exceeds the maximum {max_delivery} days.")

        # Budget only maps to a field for professionals in this dataset
        # (hourly_rate_inr). Suppliers/opportunities carry no per-unit price,
        # so a stated budget can't be verified against them here - that gap
        # is surfaced as a top-level risk note by the orchestrator instead of
        # silently rejecting or silently ignoring the constraint.
        if budget is not None and "hourly_rate_inr" in r:
            rate = r.get("hourly_rate_inr")
            if rate is not None and rate > budget:
                reasons.append(f"Hourly rate {rate} exceeds the stated budget {budget}.")

        if require_immediate and "availability" in r:
            availability = (r.get("availability") or "").strip().lower()
            if availability != "available":
                reasons.append(
                    f"Availability is '{r.get('availability')}', not immediately available as required."
                )

        # An opportunity/listing that's closed is factually unavailable
        # regardless of what the user asked for - this is a data-integrity
        # check, not a stated preference, so it's always enforced.
        if "status" in r:
            status = (r.get("status") or "").strip().lower()
            if status != "open":
                reasons.append(f"Opportunity status is '{r.get('status')}', not open.")

        if reasons:
            rejected.append({"id": r.get("id"), "name": r.get("name"), "reasons": reasons})
        else:
            passed.append(r)

    return {"passed": passed, "rejected": rejected}
