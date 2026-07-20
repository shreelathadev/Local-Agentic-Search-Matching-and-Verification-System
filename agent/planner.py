"""
planner.py

Required by section 4.2: before searching, the agent should produce a short
execution plan. This is deliberately NOT another LLM call - the plan's value
here is that it's followed and shown to the user, not that it's creative.
A fixed, dependable template that matches the PDF's own example is more
trustworthy (and testable) than asking a 1.7B model to invent one each time.
"""

from typing import Dict, List

from agent.schema import StructuredRequirement


def get_execution_plan(structured: StructuredRequirement) -> Dict[str, List[str]]:
    """Return the ordered list of steps the orchestrator will follow."""
    entity_label = {
        "supplier": "suppliers",
        "professional": "professionals",
        "opportunity": "opportunities",
    }.get(structured.entity_type, structured.entity_type)

    steps = [
        f"Search {entity_label} by category and location.",
        "Inspect candidate capabilities, certifications, and availability.",
        "Filter out records that fail any hard requirement.",
        "Rank the remaining records using a transparent, evidence-based score.",
        "Validate every recommendation against the dataset.",
        "Correct and re-search if validation fails (up to 3 attempts).",
        "Prepare the final response, evidence, and a draft outreach message.",
    ]
    return {"steps": steps}
