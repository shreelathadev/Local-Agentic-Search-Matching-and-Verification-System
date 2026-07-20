# # test_run.py
# from tools.loader import load_all
# from tools.search import search_entities
# from tools.filters import filter_by_constraints

# # Load data dynamically
# data = load_all()

# # Find candidates matching broad search rules
# candidates = search_entities(
#     dataset=data, 
#     entity_type="opportunity", # Using 'opportunity' to query your custom opportunities.json
#     category="biodegradable food containers",
#     locations=["Karnataka", "Tamil Nadu", "Kerala", "Andhra Pradesh"]
# )
# print(f"Candidates found: {len(candidates)}")

# # Strict evaluation of constraints
# result = filter_by_constraints(candidates, {
#     "minimum_capacity": 10000,
#     "maximum_delivery_days": 30,
# })
# print(f"Passed: {len(result['passed'])}, Rejected: {len(result['rejected'])}")
# print("\nRejected Reasons Summary:")
# for rej in result["rejected"]:
#     print(f"- {rej['id']} ({rej['name']}): {rej['reasons']}")




# from your project root, python3
from tools.loader import load_all
from tools.search import search_entities
from tools.filters import filter_by_constraints
from tools.validator import validate_recommendations

data = load_all()

candidates = search_entities(data, "supplier", category="biodegradable food containers",
                              locations=["Karnataka", "Tamil Nadu", "Kerala", "Andhra Pradesh"])
print(f"Candidates found: {len(candidates)}")

result = filter_by_constraints(candidates, {
    "certifications": ["food-grade"],
    "minimum_capacity": 10000,
    "maximum_delivery_days": 30,
})
print(f"Passed: {len(result['passed'])}, Rejected: {len(result['rejected'])}")
for rej in result["rejected"][:5]:
    print(rej)