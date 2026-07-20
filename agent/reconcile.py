"""
reconcile.py

Small local models (like qwen3:1.7b) sometimes misclassify a clearly-stated
hard requirement (e.g. "food-grade") as a soft preference, or fail to expand
a vague regional phrase like "South India" into the correct concrete states
- and sometimes add states that were never mentioned at all.

The assignment is explicit: "Hard constraints must never be silently
ignored" and the agent "must not invent records or recommendations" beyond
what's grounded in the request/dataset. So we treat the parser's JSON as a
DRAFT, not ground truth, and run a deterministic (non-LLM) reconciliation
pass against the original request text before anything reaches search/filter.

This is intentionally a small, explainable rule set - not trying to be a
second parser. Its job is to catch the specific, checkable failure modes:
missed certifications and mishandled regional location phrases.
"""

import re
from typing import Dict, List, Optional

from agent.schema import StructuredRequirement

# Controlled vocabulary of certification terms we can reliably detect via
# keyword match. Extend this list as your dataset's certification fields grow.
KNOWN_CERTIFICATIONS = [
    "food-grade", "fssai", "iso-14001", "iso-9001", "oeko-tex",
    "organic", "halal", "leed",
]

# Known ambiguous multi-state region phrases and their canonical expansion.
# When a phrase like "south india" is the ONLY location info given, we
# replace whatever the model guessed with this canonical list, since
# anything else the model added wasn't actually grounded in the request text.
REGION_ALIASES: Dict[str, List[str]] = {
    "south india": ["Karnataka", "Tamil Nadu", "Kerala", "Andhra Pradesh"],
}


# Phrases that signal the user needs immediate availability, in case the
# small model doesn't reliably set require_immediate_availability itself.
URGENCY_PHRASES = ["immediately", "right away", "asap", "urgently", "as soon as possible"]

# Recovers a stated result count even when other words sit between the number
# and the entity keyword (e.g. "2 packaging design professionals"), and
# handles both digits and small spelled-out numbers (e.g. "three suppliers").
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_COUNT_PATTERN = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b(?:\s+\w+){0,3}?\s+"
    r"(suppliers?|professionals?|opportunit(?:y|ies))\b",
    re.IGNORECASE,
)


def _extract_requested_count(text: str) -> Optional[int]:
    match = _COUNT_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1).lower()
    return int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)


def reconcile_requirement(structured: StructuredRequirement) -> StructuredRequirement:
    """Deterministically correct common small-model parsing mistakes."""
    text = text_lower = structured.raw_request.lower()
    notes: List[str] = []

    # 1. Recover certifications mentioned in the request but dropped or
    #    misfiled into preferences.
    existing_certs_lower = [c.lower() for c in structured.hard_constraints.certifications]
    for cert in KNOWN_CERTIFICATIONS:
        if cert in text_lower and cert not in existing_certs_lower:
            structured.hard_constraints.certifications.append(cert)
            notes.append(
                f"Recovered certification '{cert}' from request text "
                f"(model had left it out of hard_constraints)."
            )
            # Remove a matching/contradictory preference entry if present.
            for pref_key in list(structured.preferences.keys()):
                if pref_key.lower() == cert:
                    structured.preferences.pop(pref_key)

    # 2. Expand (and correct) known ambiguous multi-state region phrases.
    #    We REPLACE rather than merge here: if the request only said
    #    "South India", any specific state the model added on its own isn't
    #    grounded in the text and should not be trusted as a stated constraint.
    for phrase, states in REGION_ALIASES.items():
        if phrase in text_lower:
            structured.hard_constraints.locations = list(states)
            notes.append(
                f"Replaced location list with canonical expansion of "
                f"'{phrase}': {states} (model's own guess was not fully grounded in the text)."
            )

    # 3. Recover "immediate availability" requirement from urgency phrasing,
    #    in case the model didn't set the flag itself.
    if not structured.hard_constraints.require_immediate_availability:
        if any(phrase in text_lower for phrase in URGENCY_PHRASES):
            structured.hard_constraints.require_immediate_availability = True
            notes.append(
                "Detected urgency phrasing in the request; set "
                "require_immediate_availability=True (model had left it unset)."
            )

    # 4. Recover the stated result count if the model missed it (defaulted
    #    to 3 instead of picking up an explicitly stated number like "2").
    recovered_count = _extract_requested_count(structured.raw_request)
    if recovered_count is not None and recovered_count != structured.requested_results:
        notes.append(
            f"Corrected requested_results from {structured.requested_results} to "
            f"{recovered_count} based on a number explicitly stated in the request text."
        )
        structured.requested_results = recovered_count

    structured.reconciliation_notes = notes

    # 5. Clean up: strip any top-level/structural field names that the model
    #    accidentally duplicated inside preferences (e.g. "requested_results").
    reserved_keys = {
        "requested_results", "locations", "certifications",
        "minimum_capacity", "maximum_delivery_days", "entity_type", "objective",
    }
    for key in list(structured.preferences.keys()):
        if key.lower() in reserved_keys:
            structured.preferences.pop(key)

    return structured
