"""
Fixed rubric for LLD submission evaluation.

Kept as plain data (not hardcoded into prompt strings scattered around)
so it's the single source of truth for both:
  - the prompt sent to the AI evaluator, and
  - validating the AI's structured response.

Per the helping guide (section 7): never ask "is this a good design?".
Instead force the model through this fixed set of criteria with
required evidence per criterion.
"""

RUBRIC_CRITERIA = [
    {
        "key": "requirement_understanding",
        "label": "Requirement Understanding",
        "description": "Does the design address the stated functional requirements and constraints?",
    },
    {
        "key": "class_responsibilities",
        "label": "Class Responsibilities",
        "description": "Does each class/object have a single, clear responsibility?",
    },
    {
        "key": "coupling_cohesion",
        "label": "Coupling / Cohesion",
        "description": "Are related behaviours grouped together, and are classes loosely coupled to each other?",
    },
    {
        "key": "encapsulation_interfaces",
        "label": "Encapsulation & Interfaces",
        "description": "Is internal state hidden appropriately, and are interfaces/abstractions used where useful?",
    },
    {
        "key": "extensibility",
        "label": "Extensibility",
        "description": "Could the design accommodate a plausible future change without a rewrite?",
    },
    {
        "key": "edge_cases",
        "label": "Edge Cases & Testability",
        "description": "Are edge cases considered, and would the design be straightforward to test?",
    },
]

SCORE_MIN = 1
SCORE_MAX = 5


def criteria_keys() -> list[str]:
    return [c["key"] for c in RUBRIC_CRITERIA]
