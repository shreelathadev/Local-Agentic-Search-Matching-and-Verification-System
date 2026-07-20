"""
loader.py

Loads the synthetic Suproc dataset from JSON and normalizes messy fields so
that downstream tools (search, filter, validate) can rely on consistent types.

Why normalization lives here and nowhere else:
The raw dataset intentionally contains things like delivery_days = "TBD" and
location = {} (missing). Rather than making every tool defensively handle
every possible raw shape, we normalize ONCE at load time and attach the
cleaned values under private "_xxx_normalized" keys, while keeping the
original raw fields untouched (so the agent can still show the user the
raw messy data if needed, e.g. "delivery_days was reported as TBD").
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"


def _normalize_delivery_days(value: Any) -> Optional[int]:
    """Return an int if delivery_days is a real number, else None (unconfirmed)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None  # e.g. "TBD"
    return None


def _normalize_location(loc: Any) -> Dict[str, Optional[str]]:
    """Return a {city, state} dict even if location is missing or malformed."""
    if not isinstance(loc, dict):
        return {"city": None, "state": None}
    return {
        "city": loc.get("city") or None,
        "state": loc.get("state") or None,
    }


def _load_json_file(filename: str) -> List[Dict]:
    path = DATASET_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_suppliers() -> List[Dict]:
    records = _load_json_file("suppliers.json")
    for r in records:
        r["_delivery_days_normalized"] = _normalize_delivery_days(r.get("delivery_days"))
        r["_location_normalized"] = _normalize_location(r.get("location"))
        r["_certifications_normalized"] = r.get("certifications") or []
        r["entity_type"] = "supplier"
    return records


def load_professionals() -> List[Dict]:
    records = _load_json_file("professionals.json")
    for r in records:
        r["_location_normalized"] = _normalize_location(r.get("location"))
        r["_certifications_normalized"] = r.get("certifications") or []
        r["entity_type"] = "professional"
    return records


def load_opportunities() -> List[Dict]:
    records = _load_json_file("opportunities.json")
    for r in records:
        r["_location_normalized"] = _normalize_location(r.get("location"))
        r["entity_type"] = "opportunity"
    return records


def load_all() -> Dict[str, List[Dict]]:
    """Load the full dataset once. Pass this dict into every tool call."""
    return {
        "supplier": load_suppliers(),
        "professional": load_professionals(),
        "opportunity": load_opportunities(),
    }


if __name__ == "__main__":
    # Quick manual sanity check: run `python tools/loader.py` from the project root.
    data = load_all()
    for entity_type, records in data.items():
        print(f"{entity_type}: {len(records)} records loaded")
    tbd = [r["id"] for r in data["supplier"] if r["_delivery_days_normalized"] is None]
    print("Suppliers with unconfirmed delivery time:", tbd)
