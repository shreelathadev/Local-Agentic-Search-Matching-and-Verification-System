from agent.orchestrator import run_agent
import json

impossible_request = (
    "We need 3 suppliers from South India for food-grade biodegradable "
    "containers, with a minimum monthly capacity of 200000 units and "
    "delivery within 30 days."
)
result = run_agent(impossible_request)
print(json.dumps({
    "recommendations": result["recommendations"],
    "validation": result["validation"],
    "correction_attempts_used": result["correction_attempts_used"],
    "recommended_next_action": result["recommended_next_action"],
    "status": result["status"],
}, indent=2))