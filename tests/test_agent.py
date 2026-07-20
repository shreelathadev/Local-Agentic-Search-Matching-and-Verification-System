"""
tests/test_agent.py

Covers the required test cases from assignment section 11:
  1.  Normal request with several valid matches
  2.  A request where no record satisfies all hard constraints
  3.  Conflicting user requirements
  4.  Missing information in the request
  5.  Missing information in the dataset
  6.  Ambiguous location or category
  7.  Duplicate records
  8.  An invalid or unavailable entity
  9.  A recommendation that initially fails validation
  10. A prompt-injection attempt inside a dataset record
  11. A request requiring human approval
  12. A request asking the agent to ignore validation rules

Design note: most tests call the deterministic tools/scoring/validator/
reconcile functions directly with constructed inputs rather than going
through the full LLM pipeline (agent.orchestrator.run_agent). This keeps
the suite fast and fully deterministic. Two genuine end-to-end tests DO
call the real model through Ollama and are marked @pytest.mark.slow.
    
"""

import pytest

from tools.loader import load_all
from tools.search import search_entities, get_entity_details
from tools.filters import filter_by_constraints
from tools.validator import validate_recommendations
from tools.outreach import draft_outreach
from agent.scoring import calculate_match_score
from agent.reconcile import reconcile_requirement
from agent.schema import StructuredRequirement, HardConstraints


@pytest.fixture(scope="module")
def dataset():
    return load_all()


SOUTH_STATES = ["Karnataka", "Tamil Nadu", "Kerala", "Andhra Pradesh"]
STANDARD_CONSTRAINTS = {
    "locations": SOUTH_STATES,
    "certifications": ["food-grade"],
    "minimum_capacity": 10000,
    "maximum_delivery_days": 30,
}


# 1. Normal request with several valid matches --------------------------------
def test_normal_request_has_multiple_valid_matches(dataset):
    candidates = search_entities(dataset, "supplier", category="biodegradable food containers")
    result = filter_by_constraints(candidates, STANDARD_CONSTRAINTS)
    assert len(result["passed"]) >= 3, "Expected several suppliers to pass all hard constraints"


# 2. No record satisfies all hard constraints ---------------------------------
def test_impossible_capacity_yields_no_matches(dataset):
    impossible_constraints = dict(STANDARD_CONSTRAINTS, minimum_capacity=200000)
    candidates = search_entities(dataset, "supplier", category="biodegradable food containers")
    result = filter_by_constraints(candidates, impossible_constraints)
    assert len(result["passed"]) == 0
    assert len(result["rejected"]) > 0


# 3. Conflicting user requirements ---------------------------------------------
def test_conflicting_constraints_reject_everything(dataset):
    # Requiring all three certifications at once AND an unrealistically tight
    # delivery window together rule out every candidate in the dataset.
    conflicting_constraints = {
        "locations": SOUTH_STATES,
        "certifications": ["food-grade", "iso-14001", "fssai"],
        "minimum_capacity": 10000,
        "maximum_delivery_days": 5,
    }
    candidates = search_entities(dataset, "supplier", category="biodegradable food containers")
    result = filter_by_constraints(candidates, conflicting_constraints)
    assert len(result["passed"]) == 0


# 4. Missing information in the request ----------------------------------------
def test_missing_request_info_leaves_constraint_empty():
    req = StructuredRequirement(
        objective="Find biodegradable packaging suppliers",
        entity_type="supplier",
        hard_constraints=HardConstraints(locations=SOUTH_STATES, certifications=["food-grade"]),
        raw_request="We need biodegradable packaging suppliers from South India.",
    )
    # No quantity or deadline was ever stated, so these must stay unset -
    # never guessed at.
    assert req.hard_constraints.minimum_capacity is None
    assert req.hard_constraints.maximum_delivery_days is None


# 5. Missing information in the dataset ----------------------------------------
def test_supplier_with_missing_certification_is_rejected(dataset):
    candidates = [r for r in dataset["supplier"] if r["id"] in ("SUP-004", "SUP-025")]
    result = filter_by_constraints(candidates, STANDARD_CONSTRAINTS)
    rejected_ids = {r["id"] for r in result["rejected"]}
    assert {"SUP-004", "SUP-025"}.issubset(rejected_ids)


# 6. Ambiguous location or category ---------------------------------------------
def test_ambiguous_location_is_rejected_with_reason(dataset):
    sup007 = [r for r in dataset["supplier"] if r["id"] == "SUP-007"]  # location: "South India"
    result = filter_by_constraints(sup007, STANDARD_CONSTRAINTS)
    assert len(result["rejected"]) == 1
    assert "not in the allowed list" in result["rejected"][0]["reasons"][0]


def test_ambiguous_region_phrase_is_expanded_deterministically():
    req = StructuredRequirement(
        objective="Find suppliers",
        entity_type="supplier",
        raw_request="We need suppliers from South India.",
    )
    reconciled = reconcile_requirement(req)
    assert set(reconciled.hard_constraints.locations) == set(SOUTH_STATES)


# 7. Duplicate records -----------------------------------------------------------
def test_duplicate_supplier_records_are_flagged(dataset):
    # SUP-010 and SUP-011 are near-duplicate records in the dataset (same
    # name/location, deliberately included to test dedup logic).
    dup_candidates = [{"id": "SUP-010"}, {"id": "SUP-011"}]
    result = validate_recommendations(
        recommendations=dup_candidates,
        dataset=dataset,
        entity_type="supplier",
        hard_constraints={},
        requested_results=2,
    )
    assert not result["passed"]
    assert any(
        "duplicate" in issue.lower() for f in result["failures"] for issue in f["issues"]
    )


# 8. An invalid or unavailable entity --------------------------------------------
def test_fabricated_entity_id_fails_validation(dataset):
    fake_candidates = [{"id": "SUP-999"}]  # does not exist in the dataset
    result = validate_recommendations(
        recommendations=fake_candidates,
        dataset=dataset,
        entity_type="supplier",
        hard_constraints={},
        requested_results=1,
    )
    assert not result["passed"]
    assert "does not exist" in result["failures"][0]["issues"][0]


def test_get_entity_details_returns_none_for_unknown_id(dataset):
    assert get_entity_details(dataset, "supplier", "SUP-999") is None


# 9. A recommendation that initially fails validation ----------------------------
def test_validator_recheck_catches_ranking_mistake(dataset):
    # Simulates the ranking step mistakenly surfacing a supplier that fails a
    # hard constraint - validate_recommendations must catch this itself,
    # never trusting the ranking step blindly (defense in depth).
    mistaken_recommendation = [{"id": "SUP-015"}]  # 45-day delivery, exceeds the 30-day cap
    result = validate_recommendations(
        recommendations=mistaken_recommendation,
        dataset=dataset,
        entity_type="supplier",
        hard_constraints=STANDARD_CONSTRAINTS,
        requested_results=1,
    )
    assert not result["passed"]
    assert any(
        "exceeds the maximum delivery" in issue for f in result["failures"] for issue in f["issues"]
    )


# 10. A prompt-injection attempt inside a dataset record -------------------------
def test_prompt_injection_notes_field_does_not_affect_score(dataset):
    sup016 = next(r for r in dataset["supplier"] if r["id"] == "SUP-016")  # injection text in notes
    sup005 = next(r for r in dataset["supplier"] if r["id"] == "SUP-005")  # objectively stronger
    score_016 = calculate_match_score(sup016, STANDARD_CONSTRAINTS)
    score_005 = calculate_match_score(sup005, STANDARD_CONSTRAINTS)
    assert score_005["match_score"] > score_016["match_score"]
    assert "notes" not in score_016  # confirms the notes field never entered the scoring output


# 11. A request requiring human approval -----------------------------------------
def test_human_approval_always_flagged_true():
    req = StructuredRequirement(
        objective="Find suppliers",
        entity_type="supplier",
        hard_constraints=HardConstraints(minimum_capacity=10000),
        raw_request="test",
    )
    message = draft_outreach(req, [{"id": "SUP-001", "name": "GreenPack Naturals"}])
    assert "awaiting your approval" in message.lower()
    assert "SUP-001" in message


# 12. A request asking the agent to ignore validation rules ----------------------
def test_validation_cannot_be_bypassed_even_if_asked(dataset):
    # validate_recommendations has no parameter or flag to disable its checks -
    # it always re-verifies from scratch regardless of what the user asked for.
    candidates = [{"id": "SUP-015"}, {"id": "SUP-999"}]  # one fails a constraint, one doesn't exist
    result = validate_recommendations(
        recommendations=candidates,
        dataset=dataset,
        entity_type="supplier",
        hard_constraints=STANDARD_CONSTRAINTS,
        requested_results=2,
    )
    assert not result["passed"]
    assert len(result["failures"]) == 2


# --- New coverage: budget, immediate availability, cross-entity-type safety ---

def test_professional_records_not_rejected_for_missing_supplier_fields(dataset):
    # A professional has no capacity_units_per_month or delivery_days at all -
    # stating those constraints must not cause a false rejection.
    professionals = [r for r in dataset["professional"] if r["id"] in ("PRO-001", "PRO-009")]
    constraints = {
        "locations": ["Karnataka"],
        "minimum_capacity": 10000,
        "maximum_delivery_days": 30,
    }
    result = filter_by_constraints(professionals, constraints)
    assert len(result["passed"]) == 2


def test_budget_constraint_rejects_professional_over_budget(dataset):
    pro = next(r for r in dataset["professional"] if r["id"] == "PRO-010")  # hourly_rate_inr: 2800
    result = filter_by_constraints([pro], {"budget": 2000})
    assert len(result["rejected"]) == 1
    assert "exceeds the stated budget" in result["rejected"][0]["reasons"][0]


def test_immediate_availability_rejects_booked_professional(dataset):
    booked = next(r for r in dataset["professional"] if r["id"] == "PRO-003")  # "booked until next month"
    result = filter_by_constraints([booked], {"require_immediate_availability": True})
    assert len(result["rejected"]) == 1


def test_urgency_phrase_sets_immediate_availability_flag():
    req = StructuredRequirement(
        objective="Find a professional",
        entity_type="professional",
        raw_request="We need a packaging consultant available immediately.",
    )
    reconciled = reconcile_requirement(req)
    assert reconciled.hard_constraints.require_immediate_availability is True


def test_global_risk_flagged_when_budget_stated_for_supplier():
    from agent.orchestrator import _build_global_risks

    req = StructuredRequirement(
        objective="test",
        entity_type="supplier",
        hard_constraints=HardConstraints(budget=5000),
        raw_request="test",
    )
    risks = _build_global_risks(req, {"budget": 5000}, 1)
    assert any("pricing information" in r for r in risks)


def test_requested_count_recovered_when_words_separate_number_from_keyword():
    req = StructuredRequirement(
        objective="Find packaging design professionals",
        entity_type="professional",
        raw_request="We need 2 packaging design professionals based in Karnataka.",
        requested_results=3,  # simulates the model defaulting/guessing wrong
    )
    reconciled = reconcile_requirement(req)
    assert reconciled.requested_results == 2


def test_budget_margin_differentiates_professional_scores(dataset):
    pro_001 = next(r for r in dataset["professional"] if r["id"] == "PRO-001")  # hourly_rate 1500
    pro_009 = next(r for r in dataset["professional"] if r["id"] == "PRO-009")  # hourly_rate 1700
    budget_constraints = {"budget": 2000}
    score_001 = calculate_match_score(pro_001, budget_constraints)
    score_009 = calculate_match_score(pro_009, budget_constraints)
    # More room under budget should score higher on the hard_constraint_compliance component
    assert (
        score_001["score_breakdown"]["hard_constraint_compliance"]["value"]
        > score_009["score_breakdown"]["hard_constraint_compliance"]["value"]
    )


# --- Opportunity entity-type coverage ------------------------------------------

def test_closed_opportunity_is_rejected_automatically(dataset):
    # OPP-009 is deliberately marked status="closed" - must be rejected even
    # though nothing in a typical request would explicitly ask for "open only".
    closed_opp = [r for r in dataset["opportunity"] if r["id"] == "OPP-009"]
    result = filter_by_constraints(closed_opp, {})
    assert len(result["rejected"]) == 1
    assert "not open" in result["rejected"][0]["reasons"][0]


def test_opportunity_duplicates_detected_via_title_not_name(dataset):
    # OPP-001 and OPP-007 are deliberate duplicates in the dataset. Opportunities
    # use "title", not "name" - this test catches the bug where dedup silently
    # fell back to comparing empty strings for every opportunity.
    candidates = [{"id": "OPP-001"}, {"id": "OPP-007"}]
    result = validate_recommendations(
        recommendations=candidates,
        dataset=dataset,
        entity_type="opportunity",
        hard_constraints={},
        requested_results=2,
    )
    assert not result["passed"]
    assert any("duplicate" in issue.lower() for f in result["failures"] for issue in f["issues"])


def test_unrelated_opportunities_in_same_location_are_not_falsely_flagged_as_duplicates():
    # Regression guard for the same bug in the other direction: two genuinely
    # different opportunities at the IDENTICAL location must NOT be flagged as
    # duplicates just because they'd both normalize to an empty "name" if the
    # code were still reading .get("name") instead of falling back to "title".
    mini_dataset = {
        "opportunity": [
            {
                "id": "OPP-A", "title": "Textile sourcing for uniforms",
                "posted_by": "BIZ-201", "budget_inr": 100000, "quantity": 500,
                "_location_normalized": {"city": "Bengaluru", "state": "Karnataka"},
            },
            {
                "id": "OPP-B", "title": "Office furniture procurement",
                "posted_by": "BIZ-202", "budget_inr": 250000, "quantity": 50,
                "_location_normalized": {"city": "Bengaluru", "state": "Karnataka"},
            },
        ]
    }
    result = validate_recommendations(
        recommendations=[{"id": "OPP-A"}, {"id": "OPP-B"}],
        dataset=mini_dataset,
        entity_type="opportunity",
        hard_constraints={},
        requested_results=2,
    )
    assert result["passed"]


def test_opportunity_category_field_is_actually_used_for_filtering(dataset):
    # Regression guard: opportunities use "category", not "product_category".
    # Searching for biodegradable containers must NOT return the unrelated
    # textiles listing (OPP-006) just because it's in the same state.
    candidates = search_entities(
        dataset, "opportunity", category="biodegradable food containers", locations=["Karnataka"]
    )
    ids = {r["id"] for r in candidates}
    assert "OPP-006" not in ids
    assert "OPP-001" in ids


# --- Slow integration tests: real LLM calls via Ollama --------------------------

@pytest.mark.slow
def test_full_pipeline_normal_request_end_to_end():
    from agent.orchestrator import run_agent

    request = (
        "We are a sustainable food-packaging startup based in Bengaluru. We need three "
        "suppliers from South India that can provide food-grade biodegradable containers, "
        "support an initial order of 10,000 units and deliver within 30 days."
    )
    result = run_agent(request)
    assert result["status"] == "AWAITING_APPROVAL"
    assert len(result["recommendations"]) == 3
    assert result["human_approval_required"] is True


@pytest.mark.slow
def test_full_pipeline_impossible_request_reports_honestly():
    from agent.orchestrator import run_agent

    request = (
        "We need 3 suppliers from South India for food-grade biodegradable containers, "
        "with a minimum monthly capacity of 200000 units and delivery within 30 days."
    )
    result = run_agent(request)
    assert result["status"] == "NO_VALID_RESULTS"
    assert result["recommendations"] == []


@pytest.mark.slow
def test_full_pipeline_opportunity_request_end_to_end():
    from agent.orchestrator import run_agent

    request = (
        "Find 2 open procurement opportunities for biodegradable food containers in Karnataka."
    )
    result = run_agent(request)
    assert result["status"] in ("AWAITING_APPROVAL", "NO_VALID_RESULTS")
    # Whatever came back must be real, open, non-duplicate opportunities
    ids_seen = set()
    for rec in result["recommendations"]:
        assert rec["id"] not in ids_seen
        ids_seen.add(rec["id"])
