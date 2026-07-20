from tools.loader import load_all
from agent.scoring import rank_candidates

data = load_all()
suppliers = [r for r in data["supplier"] if r["id"] in ["SUP-001", "SUP-005", "SUP-023", "SUP-029"]]
hard_constraints = {
    "locations": ["Karnataka", "Tamil Nadu", "Kerala", "Andhra Pradesh"],
    "certifications": ["food-grade"],
    "minimum_capacity": 10000,
    "maximum_delivery_days": 30,
}
ranked = rank_candidates(suppliers, hard_constraints)
for r in ranked:
    print(r["id"], r["match_score"], r["score_breakdown"])