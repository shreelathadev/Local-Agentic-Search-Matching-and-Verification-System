"""
search.py

Two required tools:
  - search_entities: broad first-pass retrieval by entity_type / category / location
  - get_entity_details: the ONLY trusted way to confirm a record is real

Design note: search_entities is intentionally permissive. It does NOT drop
records with missing/ambiguous locations - it lets them through as candidates.
Hard rejection happens later in filter_by_constraints, where we can log a
clear reason. This keeps "why was this excluded" fully explainable.
"""

from typing import Dict, List, Optional


def search_entities(
    dataset: Dict[str, List[Dict]],
    entity_type: str,
    category: Optional[str] = None,
    locations: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Tool: search_entities
    Retrieves candidate records of a given entity_type, optionally narrowed by
    a product/skill category keyword and a list of acceptable states.

    Args:
        dataset: the dict returned by loader.load_all()
        entity_type: "supplier" | "professional" | "opportunity"
        category: keyword matched against product_category / skills / title
        locations: list of acceptable state names (loose match, case-insensitive)

    Returns:
        List of matching raw records (with normalized fields attached).
    """
    if entity_type not in dataset:
        return []

    records = dataset[entity_type]
    results = []

    for r in records:
        if category:
            text_fields = [
                (r.get("product_category") or "").lower(),
                (r.get("category") or "").lower(),  # opportunities use this field name
                (r.get("title") or "").lower(),
            ] + [s.lower() for s in (r.get("skills") or [])]
            if not any(category.lower() in field for field in text_fields):
                continue

        if locations:
            state = r.get("_location_normalized", {}).get("state")
            allowed = [l.lower() for l in locations]
            if state is not None and state.lower() not in allowed:
                continue
            # state is None (missing/ambiguous) -> let it through as a candidate;
            # filter_by_constraints will flag and reject it with a clear reason.

        results.append(r)

    return results


def get_entity_details(
    dataset: Dict[str, List[Dict]], entity_type: str, entity_id: str
) -> Optional[Dict]:
    """
    Tool: get_entity_details
    Returns the full record for a specific entity_id, or None if it does not
    exist. This is the ONLY way the agent should confirm a record is real -
    never trust an entity_id unless it was returned by search_entities or
    verified here first.
    """
    if entity_type not in dataset:
        return None
    for r in dataset[entity_type]:
        if r.get("id") == entity_id:
            return r
    return None
