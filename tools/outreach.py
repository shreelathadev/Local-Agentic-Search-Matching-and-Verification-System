# """
# outreach.py

# Optional tool: draft_outreach
# Prepares an outreach message as TEXT ONLY. This function has no ability to
# send anything anywhere - it returns a string for the user to review and
# approve. This is the concrete embodiment of section 8's requirement.
# """

# from typing import Dict, List
# from agent.schema import StructuredRequirement


# def draft_outreach(structured: StructuredRequirement, recommendations: List[Dict]) -> str:
#     """Build a professional, dynamically-typed draft outreach message."""
#     if not recommendations:
#         return "No recommendations available to draft an outreach message."

#     ids = ", ".join(r["id"] for r in recommendations)
#     entity_type = structured.entity_type.lower()
    
#     # Clean up the subject line topic dynamically
#     # Use the extracted category if available; otherwise fall back to a clean fallback
#     topic = getattr(structured, 'category', None) or "Sustainable Procurement"
    
#     # 1. Determine target entity details based on the top recommendation
#     first_rec = recommendations[0]
#     rec_name = first_rec.get("name", "Representative")
    
#     # 2. Tailor text parameters based on the entity type
#     if entity_type == "supplier":
#         subject = f"Procurement Inquiry: B2B Supply of {topic.title()}"
#         salutation = f"Dear Team at {rec_name},"
#         body = (
#             f"We identified your profile via the Suproc platform and are highly interested "
#             f"in your packaging and manufacturing capabilities. We are reaching out to establish "
#             f"a supply relationship regarding {topic.lower()}."
#         )
#         action_ask = "Could you please share your latest catalog, standard lead times, and verification certificates?"
        
#     elif entity_type == "professional":
#         subject = f"Collaboration Inquiry: Freelance/Consulting for {topic.title()}"
#         salutation = f"Dear {rec_name},"
#         body = (
#             f"We came across your profile and expertise in {topic.lower()}. We are looking for "
#             f"qualified professional assistance and believe your background aligns closely with our technical goals."
#         )
#         action_ask = "Are you currently available for freelance or advisory engagements? If so, please let us know your standard onboarding timeline."
        
#     else:  # opportunity / projects
#         subject = f"Expression of Interest: Project {first_rec.get('id', '')} - {topic.title()}"
#         salutation = f"To the Project Coordinator for {rec_name},"
#         body = (
#             f"We are reaching out to officially express our interest in the open procurement posting "
#             f"regarding '{rec_name}'. Our team has reviewed the baseline requirements and we believe "
#             f"we are a strong candidate to fulfill this request."
#         )
#         action_ask = "Could you please advise on the next steps for formal submission or qualification evaluation?"

#     # 3. Assemble the unified template
#     message = (
#         f"Subject: {subject}\n\n"
#         f"{salutation}\n\n"
#         f"{body}\n"
#         f"{action_ask}\n\n"
#         f"Best regards,\n"
#         f"[Your Company Name]\n\n"
#         f"----------------------------------------------------------------------\n"
#         f"(Draft prepared for outreach to: {ids}. Status: AWAITING_APPROVAL. Not sent.)"
#     )
    
#     return message



"""
outreach.py

Optional tool: draft_outreach
Prepares an outreach message as TEXT ONLY. This function has no ability to
send anything anywhere - it returns a string for the user to review and
approve. This is the concrete embodiment of section 8's requirement.
"""

from typing import Dict, List
from agent.schema import StructuredRequirement


def draft_outreach(structured: StructuredRequirement, recommendations: List[Dict]) -> str:
    """Build professional, individual draft outreach messages for all recommended matches."""
    if not recommendations:
        return "No recommendations available to draft an outreach message."

    entity_type = structured.entity_type.lower()
    topic = getattr(structured, 'category', None) or "Sustainable Procurement"
    
    draft_blocks = []

    # Loop through each individual recommendation to customize their email
    for idx, rec in enumerate(recommendations, 1):
        rec_id = rec.get("id", "N/A")
        rec_name = rec.get("name", "Representative")
        
        # 1. Tailor text parameters based on the entity type
        if entity_type == "supplier":
            subject = f"Procurement Inquiry: B2B Supply of {topic.title()}"
            salutation = f"Dear Team at {rec_name},"
            body = (
                f"We identified your profile via the Suproc platform and are highly interested "
                f"in your packaging and manufacturing capabilities. We are reaching out to establish "
                f"a supply relationship regarding {topic.lower()}."
            )
            action_ask = "Could you please share your latest catalog, standard lead times, and verification certificates?"
            
        elif entity_type == "professional":
            subject = f"Collaboration Inquiry: Freelance/Consulting for {topic.title()}"
            salutation = f"Dear {rec_name},"
            body = (
                f"We came across your profile and expertise in {topic.lower()}. We are looking for "
                f"qualified professional assistance and believe your background aligns closely with our technical goals."
            )
            action_ask = "Are you currently available for freelance or advisory engagements? If so, please let us know your standard onboarding timeline."
            
        else:  # opportunity / projects
            subject = f"Expression of Interest: Project {rec_id} - {topic.title()}"
            salutation = f"To the Project Coordinator for {rec_name},"
            body = (
                f"We are reaching out to officially express our interest in the open procurement posting "
                f"regarding '{rec_name}'. Our team has reviewed the baseline requirements and we believe "
                f"we are a strong candidate to fulfill this request."
            )
            action_ask = "Could you please advise on the next steps for formal submission or qualification evaluation?"

        # 2. Assemble a single clean email template block
        block = (
            f"--- DRAFT {idx} (Target: {rec_id} - {rec_name}) ---\n"
            f"Subject: {subject}\n\n"
            f"{salutation}\n\n"
            f"{body}\n"
            f"{action_ask}\n\n"
            f"Best regards,\n"
            f"[Your Company Name]\n"
        )
        draft_blocks.append(block)
    
    # 3. Join all individual email blocks into one clear presentation
    header = "======================================================================\n"
    footer = f"\n(Drafts prepared for outreach to: {', '.join(r['id'] for r in recommendations)}. Status: AWAITING_APPROVAL. Not sent.)"
    
    return "\n\n".join(draft_blocks) + "\n----------------------------------------------------------------------" + footer