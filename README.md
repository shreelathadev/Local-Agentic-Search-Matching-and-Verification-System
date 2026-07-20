# Suproc Agent - Local Agentic Search, Matching and Verification System

An AI agent that turns a free-text business request into a structured requirement,
searches a local synthetic Suproc-style dataset, ranks candidates with a transparent
scoring formula, verifies its own recommendations deterministically, and prepares a
next action for a human to approve. It never sends, invites, or commits to anything
on its own.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Pull the model (see "Model used" below for why 1.7B, not 4B)
ollama pull qwen3:1.7b

# 3. Run the agent
python main.py "We are a sustainable food-packaging startup based in Bengaluru. We need
three suppliers from South India that can provide food-grade biodegradable containers,
support an initial order of 10,000 units and deliver within 30 days."

# 4. Run the test suite
python -m pytest tests/ -v                # everything, including 2 real LLM calls (~1-2 min)
python -m pytest tests/ -m "not slow" -v  # fast deterministic subset only (<1 sec)
```

### System requirements
- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally
- ~2-4GB free disk space for the model
- No GPU required, but one helps (see "Known limitations")

## Model used

**`qwen3:1.7b`** (not the recommended `qwen3:4b`).

This was a deliberate, tested decision, not a shortcut. On this development machine
(NVIDIA RTX 3050, 4GB VRAM), `qwen3:4b` (3.5GB) did not fully fit in available VRAM and
Ollama split execution 33%/67% between CPU and GPU, making single requirement-parsing
calls take 10-25+ minutes - unworkable for iterative development or a live demo.
`qwen3:1.7b` fits fully in available VRAM, runs in seconds, and - after the reconciliation
layer described below - produces reliably correct structured output for this task. This
tradeoff is exactly what the assignment's "low-resource model" option anticipates.

## Architecture

```
User request (free text)
        |
        v
[1] parse_requirement()      <- the ONLY LLM call in the entire pipeline
        |                        (agent/parser.py, via Ollama + qwen3:1.7b)
        v
[2] reconcile_requirement()  <- deterministic correction of common small-model
        |                        parsing mistakes (agent/reconcile.py)
        v
[3] get_execution_plan()     <- fixed, explainable plan (agent/planner.py)
        v
[4] search_entities()        <- broad category-based retrieval (tools/search.py)
        v
[5] filter_by_constraints()  <- hard-constraint enforcement + reasons (tools/filters.py)
        v
[6] rank_candidates()        <- transparent weighted scoring (agent/scoring.py)
        v
[7] validate_recommendations() <- independent re-check from scratch (tools/validator.py)
        v
    passed? --no--> drop failing IDs, retry from [4] (max 3 attempts)
        |yes
        v
[8] draft_outreach()         <- prepares text only, never sends (tools/outreach.py)
        v
Final structured output + "AWAITING_APPROVAL" status
```

**The one rule this whole design follows:** the LLM is used exactly once, to interpret
free text into structure. Everything that needs to be reliable - retrieval, filtering,
scoring, validation, correction - is plain, testable Python. The model proposes; the
code verifies.

### Why a reconciliation layer exists

Qwen3 1.7B is small, and testing surfaced two consistent failure modes: it sometimes
classified a clearly-stated hard requirement (e.g. "food-grade") as a soft preference
instead of a hard constraint, and it inconsistently expanded regional phrases like
"South India" into the correct four states. Rather than trying to prompt-engineer these
away entirely (which is unreliable with a model this size), `agent/reconcile.py` runs
a small, explainable, deterministic rule set against the *original request text* after
parsing, and corrects both issues before anything reaches search or filtering. Every
correction is logged in `reconciliation_notes` in the final output, so the correction is
visible, not silent - directly satisfying the requirement that hard constraints must
never be silently ignored.

## Tools

| Tool | File | Required? |
|---|---|---|
| `search_entities` | `tools/search.py` | Required |
| `get_entity_details` | `tools/search.py` | Required |
| `filter_by_constraints` | `tools/filters.py` | Required |
| `validate_recommendations` | `tools/validator.py` | Required |
| `calculate_match_score` / `rank_candidates` | `agent/scoring.py` | Optional |
| `draft_outreach` | `tools/outreach.py` | Optional |

## Match scoring (section 6 formula)

| Component | Weight | Computed from |
|---|---|---|
| Product/skill relevance | 30% | Category match (already enforced by search) |
| Location suitability | 20% | `_location_normalized.state` vs requested states |
| Hard-constraint compliance | 25% | Margin above/below capacity, delivery, certification requirements |
| Availability/capacity | 15% | `capacity_units_per_month`, normalized against the candidate group's max |
| Reputation/performance | 10% | `rating` blended with `past_interactions` as a confidence signal |

Every component traces back to a specific dataset field - never an arbitrary number.
`hard_constraint_compliance` in particular measures *margin*, not just pass/fail, so two
candidates that both technically qualify still rank apart (e.g. 60,000 capacity against
a 10,000 minimum scores higher than exactly 10,000).

## Validation and correction logic

`validate_recommendations` independently re-derives every check from the dataset -
existence, each hard constraint, duplicates (by normalized name + location, not just
ID), and whether enough valid results exist - regardless of what the ranking step
produced. If validation fails, the orchestrator drops the failing IDs and retries with
the next-best ranked candidates, up to 3 attempts. It never relaxes a hard constraint to
force a result, and if fewer valid matches exist than requested, it says so honestly
instead of fabricating one.

## Dataset

Synthetic data in `dataset/`: 32 suppliers, 15 professionals, 10 opportunities/projects.
Deliberately includes:

| Flaw | Example record(s) |
|---|---|
| Missing certification field | SUP-004, SUP-025 |
| Certification present but incomplete | SUP-014 |
| Non-numeric delivery time (`"TBD"`) | SUP-006 |
| Ambiguous location (`"South India"`) | SUP-007, OPP-010 |
| Missing location entirely | SUP-032, PRO-013 |
| Near-duplicate spelling variant | SUP-010 / SUP-011 |
| Conflicting category/certification | SUP-008 |
| Prompt-injection attempt in a text field | SUP-016 (`notes` field) |
| Boundary/off-by-one cases | SUP-010 (exactly 30 days), SUP-028 (31 days) |
| Duplicate opportunity listing | OPP-007 |
| Closed/unavailable listing | OPP-009 |
| Unrelated decoy category records | SUP-019/020/027, PRO-004/014, OPP-006 |

## Testing

28 automated tests in `tests/test_agent.py`, covering every scenario listed in the
assignment's section 11, plus additional coverage added while testing each entity
type end to end: budget constraints, immediate-availability constraints, opportunity
status enforcement, and entity-appropriate duplicate detection (name+location for
suppliers/professionals, poster+budget+quantity+location for opportunities, since
opportunity titles can legitimately reword the same underlying listing).

**Result: 28/28 passing.**

25 tests are fully deterministic (no LLM call, run in under a second). 3 are true
end-to-end integration tests through the real model (marked `@pytest.mark.slow`, one
per entity type), and all pass reliably.

## Known limitations

- **All three entity types (supplier, professional, opportunity) were tested end to
  end**, not assumed to work from generic code. This surfaced and fixed several real
  bugs specific to entity types beyond suppliers: capacity/delivery checks that don't
  apply to professionals, budget/availability checks that only make sense for
  professionals, opportunities using a `category` field the category-matching logic
  didn't originally check (silently returning unrelated categories), opportunities
  needing a mandatory `status == "open"` check that nothing previously enforced, and
  duplicate detection needing an entity-appropriate identity key (opportunity titles
  can legitimately differ in wording for the same underlying listing, so poster +
  budget + quantity + location is used instead of title text).
- **The correction-retry loop can be inefficient**: if a candidate set doesn't change
  between attempts (e.g. the only shortfall is a duplicate that will always be there),
  it still uses all 3 attempts before giving up, rather than detecting no progress and
  stopping early. Functionally harmless (never fabricates a result), just not optimal.
- **Small-model parsing errors**: `qwen3:1.7b` occasionally misclassifies a hard
  constraint as a preference, mis-expands a regional phrase, misses an explicitly
  stated result count (e.g. defaulting to 3 when the user said "2"), or echoes a stray
  number into `preferences` that isn't meaningful (e.g. `{"budget": 100}` on a request
  with no such figure). Mitigated (not eliminated) by the deterministic reconciliation
  layer, which currently only knows about a fixed vocabulary of certifications, one
  regional alias ("South India"), a short list of urgency phrases, and a regex for
  stated counts. Phrasing outside those patterns would not be auto-corrected.
- **Duplicate detection** normalizes names by removing whitespace/punctuation, which
  catches spacing variants (e.g. "Salem Biocontainers" vs "Salem Bio Containers") but
  not genuine typos or reordered words.
- **Category matching** uses keyword overlap between the request and the dataset's own
  category/skill vocabulary, not semantic/embedding similarity - an oddly-phrased
  request for an existing category could fail to match if it shares no keywords with it.
- **Budget is only enforceable against professionals** in this dataset (via
  `hourly_rate_inr`) - supplier and opportunity records carry no per-unit price field.
  A stated budget for those entity types is preserved in the structured requirement
  (never silently dropped) and surfaced as a top-level risk/caveat instead of being
  checked against nonexistent data.
- **GPU/VRAM constraints**: developed and tested on a 4GB VRAM laptop GPU, which is why
  `qwen3:1.7b` was chosen over the recommended `qwen3:4b`.
- **Qwen3 thinking mode**: Qwen3 models default to emitting `<think>...</think>`
  reasoning blocks. The parser requests `think=False` and constrains output with
  `format="json"`, and strips any `<think>` block as a safety net, but this is a
  known model-specific quirk worth flagging.
