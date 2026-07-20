"""
outreach.py

Optional tool: draft_outreach
Prepares an outreach message as TEXT ONLY. This function has no ability to
send anything anywhere - it returns a string for the user to review and
approve. This is the concrete embodiment of section 8's requirement.

Entity-aware framing matters here: a "supplier" match means the agent is
procuring FROM them (ask about capacity/certs/lead times). A "professional"
match means confirming rate/availability, not "capacity". An "opportunity"
match is the OPPOSITE direction - the agent is expressing interest in
BIDDING ON someone else's listing, not asking them for their capabilities.
"""

from typing import Dict, List, Optional

from agent.schema import StructuredRequirement


def draft_outreach(
    structured: StructuredRequirement,
    recommendations: List[Dict],
    category: Optional[str] = None,
) -> str:
    """Build individual, entity-aware, evidence-grounded draft messages for each match."""
    if not recommendations:
        return "No recommendations available to draft an outreach message."

    entity_type = structured.entity_type.lower()
    # Use the actually-matched category (passed in from the orchestrator) rather
    # than a generic placeholder, so the subject line reflects the real request.
    topic = category or structured.objective.strip().rstrip(".").split(".")[0][:60] or "your requirement"

    draft_blocks = []

    for idx, rec in enumerate(recommendations, 1):
        rec_id = rec.get("id", "N/A")
        rec_name = rec.get("name") or "Representative"
        # Ground the draft in the specific evidence already gathered for this
        # match, instead of a purely generic message - e.g. references the
        # actual reported capacity/delivery/rate rather than asking blind.
        evidence_line = "; ".join(e.rstrip(".") for e in rec.get("evidence", [])[:2])
        evidence_sentence = f" We noted the following from your profile: {evidence_line}." if evidence_line else ""

        if entity_type == "supplier":
            subject = f"Procurement Inquiry: Supply of {topic.title()}"
            salutation = f"Dear Team at {rec_name},"
            body = (
                f"We identified your profile via the Suproc platform and are interested in your "
                f"packaging and manufacturing capabilities regarding {topic.lower()}.{evidence_sentence}"
            )
            action_ask = "Could you please confirm your current capacity, certifications, and lead times for our requirement?"

        elif entity_type == "professional":
            subject = f"Engagement Inquiry: {topic.title()}"
            salutation = f"Dear {rec_name},"
            body = (
                f"We came across your profile and expertise in {topic.lower()}.{evidence_sentence} "
                f"We are looking for qualified support and believe your background aligns with our needs."
            )
            action_ask = "Are you currently available for this engagement? If so, could you confirm your rate and availability?"

        else:  # opportunity - direction is reversed: expressing interest in THEIR listing
            subject = f"Expression of Interest: {rec_name}"
            salutation = f"To the Procurement Team for '{rec_name}',"
            body = (
                f"We are writing to express interest in this opportunity regarding {topic.lower()}."
                f"{evidence_sentence} We believe we can meet the stated requirements."
            )
            action_ask = "Could you advise on next steps for formal submission or qualification?"

        block = (
            f"--- DRAFT {idx} (Target: {rec_id} - {rec_name}) ---\n"
            f"Subject: {subject}\n\n"
            f"{salutation}\n\n"
            f"{body}\n"
            f"{action_ask}\n\n"
            f"Best regards,\n[Your Company Name]"
        )
        draft_blocks.append(block)

    ids = ", ".join(r["id"] for r in recommendations)
    footer = f"\n(Drafts prepared for outreach to: {ids}. Not sent - awaiting your approval.)"

    return "\n\n".join(draft_blocks) + "\n" + ("-" * 70) + footer