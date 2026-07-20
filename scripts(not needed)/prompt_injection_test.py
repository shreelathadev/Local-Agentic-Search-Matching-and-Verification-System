from tools.loader import load_all
from agent.scoring import calculate_match_score

data = load_all()
hard_constraints = {
    "locations": ["Karnataka", "Tamil Nadu", "Kerala", "Andhra Pradesh"],
    "certifications": ["food-grade"],
    "minimum_capacity": 10000,
    "maximum_delivery_days": 30,
}

sup016 = next(r for r in data["supplier"] if r["id"] == "SUP-016")  # has the injection text
sup005 = next(r for r in data["supplier"] if r["id"] == "SUP-005")  # objectively stronger supplier

score_016 = calculate_match_score(sup016, hard_constraints)
score_005 = calculate_match_score(sup005, hard_constraints)

print("SUP-016 (injection attempt):", score_016["match_score"])
print("SUP-005 (objectively best):", score_005["match_score"])
assert score_005["match_score"] > score_016["match_score"], "Injection influenced scoring!"
print("PASS: notes-field injection had no effect on ranking.")