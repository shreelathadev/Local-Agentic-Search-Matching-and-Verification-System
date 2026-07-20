"""
parser.py

Turns a free-text business request into a StructuredRequirement using Qwen3
via Ollama. This is the ONLY place in the agent where the LLM's raw text
output gets trusted at all - and even here, it's immediately validated
against the Pydantic schema before anything downstream sees it.

If the model returns invalid JSON or JSON that fails schema validation, we
feed the exact error back to the model and ask it to correct itself
(same "give it the exact failure reason" pattern the assignment requires
for the validator, applied here too).
"""

import json
import re

import ollama
from pydantic import ValidationError

from agent.reconcile import reconcile_requirement
from agent.schema import StructuredRequirement

MODEL_NAME = "qwen3:1.7b"  # switched from qwen3:4b - fits fully in 4GB VRAM on this machine
                            # (4b was splitting 33/67 CPU/GPU and running slowly). Note this
                            # choice in the README under "model used" / known limitations.

SYSTEM_PROMPT = """You are the requirement-parsing module inside a business search agent \
called Suproc. Convert the user's business request into a single JSON object and \
return ONLY that JSON object - no markdown code fences, no explanation, no extra text.

Schema:
{
  "objective": "<one sentence describing what the user wants>",
  "entity_type": "supplier" | "professional" | "opportunity",
  "hard_constraints": {
    "locations": ["<state name>", ...],
    "certifications": ["<certification>", ...],
    "minimum_capacity": <integer or null>,
    "maximum_delivery_days": <integer or null>,
    "budget": <integer or null, e.g. a stated hourly rate or price ceiling>,
    "require_immediate_availability": <true only if the user said "immediately"/"right away"/"urgently", else false>
  },
  "preferences": { "<preference_name>": true | false | "<value>" },
  "requested_results": <integer>
}

Rules:
- entity_type: choose "supplier" for businesses/vendors/manufacturers, "professional" \
for individual freelancers/consultants/experts, "opportunity" for projects/bounties/procurement \
listings being searched for.
- Only put something in hard_constraints if the user stated it as a REQUIREMENT \
(e.g. "must be food-grade", "within 30 days"). Nice-to-haves go in preferences instead.
- Never invent a constraint the user did not mention or imply.
- If requested_results is not stated, default to 3.
- If a location, quantity, deadline, or budget is vague or missing, leave that field \
empty/null rather than guessing a specific value.
"""


def _extract_json(text: str) -> str:
    """
    Clean up the model's raw output before JSON parsing:
      1. Strip Qwen3 <think>...</think> reasoning blocks (thinking mode is on
         by default and will otherwise sit in front of the actual JSON).
      2. Strip markdown code fences if the model wrapped its JSON in them.
    """
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return text


def parse_requirement(user_request: str, max_attempts: int = 3) -> StructuredRequirement:
    """
    Calls Qwen3 to parse the user's request, validating against the Pydantic
    schema. Retries up to max_attempts times, feeding back the exact error
    on failure, mirroring the correction-loop pattern used in validation.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_request},
    ]

    last_error = None
    for attempt in range(1, max_attempts + 1):
        print(f"[parser] Calling {MODEL_NAME} (attempt {attempt}/{max_attempts})... "
              f"this can take 30-90s on the first call while the model loads.")
        response = ollama.chat(
            model=MODEL_NAME,
            messages=messages,
            think=False,       # ask nicely to skip thinking mode...
            format="json",     # ...and back it up by constraining output to valid JSON,
                                # which structurally prevents a <think> preamble either way
            options={"num_predict": -1},  # don't let a token cap cut off the answer
        )
        raw_text = response["message"]["content"]
        print(f"[parser] Response received ({len(raw_text)} chars).")
        json_text = _extract_json(raw_text)

        try:
            data = json.loads(json_text)
            data["raw_request"] = user_request
            structured = StructuredRequirement(**data)
            return reconcile_requirement(structured)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({
                "role": "user",
                "content": (
                    f"That was not valid JSON matching the required schema. "
                    f"Error: {e}\n"
                    f"Return ONLY the corrected JSON object, nothing else."
                ),
            })

    raise ValueError(
        f"Failed to parse a valid requirement after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )


if __name__ == "__main__":
    # Manual test: run `python -m agent.parser` from the project root.
    example_request = (
        "We are a sustainable food-packaging startup based in Bengaluru. We need three "
        "suppliers from South India that can provide food-grade biodegradable containers, "
        "support an initial order of 10,000 units and deliver within 30 days."
    )
    result = parse_requirement(example_request)
    print(result.model_dump_json(indent=2))
