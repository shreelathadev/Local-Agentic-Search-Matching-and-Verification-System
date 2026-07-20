"""
orchestrator.py

The main agent loop. Chains together every piece built so far:

  parse_requirement (LLM, once)
    -> get_execution_plan (fixed, deterministic)
    -> search_entities (tool)
    -> filter_by_constraints (tool)
    -> rank_candidates / calculate_match_score (deterministic)
    -> validate_recommendations (tool, deterministic)
    -> correct & retry (up to MAX_CORRECTION_ATTEMPTS)
    -> draft_outreach (tool, prepares only, never sends)
    -> final structured output (section 9 of the assignment)

IMPORTANT: the LLM is called exactly ONCE in this whole pipeline, inside
parse_requirement. Everything after that - search, filter, ranking,
validation, correction, output assembly - is plain Python. This is the
"clear separation between the model and the tools" the assignment asks for.
"""

from typing import Any, Dict, List, Optional

from agent.parser import parse_requirement
from agent.planner import get_execution_plan
from agent.scoring import rank_candidates
from agent.schema import StructuredRequirement
from tools.loader import load_all
from tools.search import search_entities, get_entity_details
from tools.filters import filter_by_constraints
from tools.validator import validate_recommendations
from tools.outreach import draft_outreach

MAX_CORRECTION_ATTEMPTS = 3

# Words to ignore when matching the request text against dataset categories/skills.
_STOPWORDS = {
    "the", "a", "an", "for", "and", "or", "of", "to", "in", "on", "with",
    "that", "this", "from", "by", "is", "are", "we", "our", "need", "needs",
    "within", "days", "units",
}


def _infer_category(dataset_records: List[Dict], text: str) -> Optional[str]:
    """
    Pick the dataset's own product_category/skill value with the strongest
    keyword overlap against the request text. Deterministic and explainable -
    not a second LLM call, not fuzzy embedding matching.
    """
    text_words = {w.strip(".,") for w in text.lower().split()} - _STOPWORDS

    candidate_categories = set()
    for r in dataset_records:
        cat = r.get("product_category")
        if cat:
            candidate_categories.add(cat)
        # Opportunities use "category" instead of "product_category" - without
        # this, category inference silently finds nothing for opportunities
        # and every opportunity in the searched locations gets through
        # regardless of subject matter.
        opp_cat = r.get("category")
        if opp_cat:
            candidate_categories.add(opp_cat)
        for s in r.get("skills") or []:
            candidate_categories.add(s)

    best_category, best_overlap = None, 0
    for cat in candidate_categories:
        cat_words = set(cat.lower().split()) - _STOPWORDS
        overlap = len(cat_words & text_words)
        if overlap > best_overlap:
            best_overlap, best_category = overlap, cat

    return best_category  # None if nothing overlapped


def _build_evidence(record: Dict, hard_constraints: Dict[str, Any]) -> List[str]:
    """Plain-language evidence strings, each traceable to a specific field."""
    evidence = []
    state = record.get("_location_normalized", {}).get("state")
    if state:
        evidence.append(f"Located in {state}.")
    certs = record.get("_certifications_normalized", [])
    if certs:
        evidence.append(f"Holds certification(s): {', '.join(certs)}.")
    capacity = record.get("capacity_units_per_month")
    if capacity is not None:
        evidence.append(f"Reports a capacity of {capacity} units/month.")
    delivery = record.get("_delivery_days_normalized")
    if delivery is not None:
        evidence.append(f"Reports a delivery time of {delivery} days.")
    rating = record.get("rating")
    if rating is not None:
        evidence.append(
            f"Has a rating of {rating}/5 from {record.get('past_interactions', 0)} past interaction(s)."
        )
    hourly_rate = record.get("hourly_rate_inr")
    if hourly_rate is not None:
        evidence.append(f"Hourly rate: {hourly_rate} INR.")
    availability = record.get("availability")
    if availability is not None:
        evidence.append(f"Availability: {availability}.")
    # Opportunity-specific fields
    if "budget_inr" in record and record.get("budget_inr") is not None:
        evidence.append(f"Budget: {record['budget_inr']} INR.")
    if "quantity" in record and record.get("quantity") is not None:
        evidence.append(f"Quantity: {record['quantity']} units.")
    if "deadline_days" in record and record.get("deadline_days") is not None:
        evidence.append(f"Deadline: {record['deadline_days']} days.")
    if "status" in record and record.get("status") is not None:
        evidence.append(f"Status: {record['status']}.")
    return evidence


def _build_record_risks(record: Dict, hard_constraints: Dict[str, Any]) -> List[str]:
    """
    Flags cases that TECHNICALLY pass validation but are worth a human's
    attention - narrow margins, thin track records, etc. This is what
    section 9's "Risks or uncertainties" field is asking for: honesty about
    confidence, not just a pass/fail badge.
    """
    risks = []

    max_delivery = hard_constraints.get("maximum_delivery_days")
    delivery = record.get("_delivery_days_normalized")
    if max_delivery is not None and delivery is not None:
        margin = max_delivery - delivery
        if 0 <= margin <= 3:
            risks.append(
                f"Delivery time ({delivery} days) is close to the maximum allowed "
                f"({max_delivery} days) - little buffer if there are delays."
            )

    min_capacity = hard_constraints.get("minimum_capacity")
    capacity = record.get("capacity_units_per_month")
    if min_capacity is not None and capacity is not None and capacity < min_capacity * 1.2:
        risks.append(
            f"Capacity ({capacity}) is close to the minimum required ({min_capacity}) - "
            f"little headroom for reorders or scale-up."
        )

    past_interactions = record.get("past_interactions")
    if past_interactions is not None and past_interactions < 5:
        risks.append(f"Limited track record on file ({past_interactions} past interaction(s)).")

    deadline_days = record.get("deadline_days")
    if deadline_days is not None and deadline_days <= 10:
        risks.append(f"Deadline is only {deadline_days} days away - tight turnaround.")

    return risks


def _build_global_risks(structured, hard_constraints: Dict[str, Any], correction_attempts: int) -> List[str]:
    """Risks about the search/interpretation as a whole, not any one record."""
    risks = []

    if structured.reconciliation_notes:
        risks.append(
            "The parsed requirement needed automatic correction (see "
            "reconciliation_notes) - recommend a human double-check the "
            "interpreted requirement before proceeding."
        )

    if correction_attempts > 1:
        risks.append(
            f"Validation failed on the first attempt and required "
            f"{correction_attempts} attempts before a valid result set was found."
        )

    budget = hard_constraints.get("budget")
    if budget is not None and structured.entity_type == "supplier":
        risks.append(
            f"A budget of {budget} was stated, but supplier records in this dataset do "
            f"not include pricing information - budget could not be verified against "
            f"the dataset and should be confirmed directly during outreach."
        )
    elif budget is not None and structured.entity_type == "opportunity":
        risks.append(
            f"A budget of {budget} was stated. Opportunity records do list their own "
            f"budget_inr, but whether the user wants a floor or a ceiling on that value "
            f"is ambiguous, so this constraint was not automatically enforced - review "
            f"the listed budget_inr on each match manually."
        )

    return risks


def run_agent(
    user_request: Optional[str] = None,
    structured_requirement: Optional[StructuredRequirement] = None,
) -> Dict[str, Any]:
    """
    Runs the full pipeline end to end and returns the section-9 style output.

    Pass either:
      - user_request: free text, will be parsed via the LLM (real usage), OR
      - structured_requirement: a pre-built StructuredRequirement, which skips
        the LLM entirely. This exists so automated tests can exercise the
        deterministic search/filter/rank/validate pipeline quickly and
        reliably, without depending on a local model being loaded.
    """
    if structured_requirement is None and user_request is None:
        raise ValueError("Provide either user_request or structured_requirement.")

    dataset = load_all()

    # Step 1: Requirement understanding (the ONLY LLM call in this pipeline,
    # and only if we weren't handed an already-structured requirement)
    structured = structured_requirement or parse_requirement(user_request)
    hard_constraints = structured.hard_constraints.model_dump()
    locations = hard_constraints.get("locations") or None

    # Step 2: Planning
    plan = get_execution_plan(structured)

    inferred_category = _infer_category(
        dataset.get(structured.entity_type, []),
        f"{structured.objective} {structured.raw_request}",
    )

    validation_result: Dict[str, Any] = {}
    rejected_log: List[Dict] = []
    ranked: List[Dict] = []
    attempt = 0

    # Steps 3-6: search -> filter -> rank -> validate, with correction attempts
    while attempt < MAX_CORRECTION_ATTEMPTS:
        attempt += 1

        candidates = search_entities(
            dataset, structured.entity_type, category=inferred_category, locations=None,
            # Note: location is intentionally NOT enforced here. It's enforced
            # (and logged with a reason) exclusively in filter_by_constraints
            # below, so that every location-based rejection - including
            # ambiguous values like "South India" or an out-of-scope state -
            # is visible in missing_or_rejected_information instead of
            # silently disappearing before the filter step ever sees it.
        )
        filter_result = filter_by_constraints(candidates, hard_constraints)
        rejected_log = filter_result["rejected"]

        ranked = rank_candidates(filter_result["passed"], hard_constraints)
        top_n = ranked[: structured.requested_results]

        validation_result = validate_recommendations(
            recommendations=top_n,
            dataset=dataset,
            entity_type=structured.entity_type,
            hard_constraints=hard_constraints,
            requested_results=structured.requested_results,
        )

        if validation_result["passed"]:
            ranked = top_n
            break

        # Correction: drop whatever failed validation and try the next-best
        # ranked candidates instead - never silently relax a hard constraint.
        failing_ids = {f["id"] for f in validation_result["failures"]}
        ranked = [r for r in ranked if r["id"] not in failing_ids]
        # not enough candidates left even after removing failures -> nothing
        # more to gain from another identical search, so stop here honestly.
        if len(ranked) < structured.requested_results and attempt == MAX_CORRECTION_ATTEMPTS:
            break

    final_recommendations = ranked[: structured.requested_results]

    enriched = []
    for rec in final_recommendations:
        full_record = get_entity_details(dataset, structured.entity_type, rec["id"])
        enriched.append({
            "id": rec["id"],
            "name": rec.get("name"),
            "match_score": rec["match_score"],
            "score_breakdown": rec["score_breakdown"],
            "evidence": _build_evidence(full_record, hard_constraints),
            "risks": _build_record_risks(full_record, hard_constraints),
        })

    global_risks = _build_global_risks(structured, hard_constraints, attempt)

    outreach_message = None
    if enriched:
        outreach_message = draft_outreach(structured, enriched, category=inferred_category)

    final_count = len(enriched)
    requested = structured.requested_results
    entity_plural = {
        "supplier": "suppliers",
        "professional": "professionals",
        "opportunity": "opportunities",
    }.get(structured.entity_type, f"{structured.entity_type}s")

    if final_count < requested:
        next_action = (
            f"Only {final_count} of the {requested} requested {structured.entity_type}(s) "
            f"could be validated against all hard constraints. Recommend either relaxing a "
            f"stated preference or searching again with adjusted criteria."
        )
    else:
        ids = ", ".join(r["id"] for r in enriched)
        next_action = f"Send a procurement enquiry to {entity_plural} {ids}."

    return {
        "interpreted_requirement": {
            "objective": structured.objective,
            "entity_type": structured.entity_type,
            "hard_constraints": hard_constraints,
            "preferences": structured.preferences,
            "requested_results": requested,
        },
        "reconciliation_notes": structured.reconciliation_notes,
        "plan_followed": plan["steps"],
        "matched_category": inferred_category,
        "recommendations": enriched,
        "constraints_checked": hard_constraints,
        "missing_or_rejected_information": rejected_log,
        "risks_or_uncertainties": global_risks,
        "validation": validation_result,
        "correction_attempts_used": attempt,
        "recommended_next_action": next_action,
        "draft_outreach_message": outreach_message,
        "human_approval_required": True,
        "status": "AWAITING_APPROVAL" if enriched else "NO_VALID_RESULTS",
    }


if __name__ == "__main__":
    import json

    example_request = (
        "We are a sustainable food-packaging startup based in Bengaluru. We need three "
        "suppliers from South India that can provide food-grade biodegradable containers, "
        "support an initial order of 10,000 units and deliver within 30 days."
    )
    output = run_agent(example_request)
    print(json.dumps(output, indent=2))
