from sqlalchemy.orm import Session

from app.models.domain import Problem

PROBLEMS = [
    {
        "title": "Design a Parking Lot",
        "prompt": (
            "Design a parking lot system that supports multiple vehicle types "
            "(motorcycle, car, bus) and multiple spot sizes."
        ),
        "requirements": (
            "- Assign a vehicle to the smallest available spot that fits it\n"
            "- Track availability per floor and overall\n"
            "- Compute a parking fee based on duration and vehicle type\n"
            "- Support entry and exit (vehicle leaving frees the spot)"
        ),
        "constraints": (
            "- A bus can only park in a large spot\n"
            "- The lot has multiple floors\n"
            "- Should be easy to add a new vehicle type later"
        ),
    },
    {
        "title": "Design an Elevator System",
        "prompt": (
            "Design the control system for a bank of elevators in a building."
        ),
        "requirements": (
            "- Handle up/down requests from a floor\n"
            "- Handle destination requests from inside an elevator\n"
            "- Decide which elevator should service a new request\n"
            "- Support multiple elevators operating independently"
        ),
        "constraints": (
            "- Elevators have a max capacity\n"
            "- Should be extensible to a smarter dispatch strategy later\n"
            "- Consider what happens if two requests arrive at once"
        ),
    },
    {
        "title": "Design a Vending Machine",
        "prompt": (
            "Design a vending machine that sells multiple products and accepts "
            "coins/notes as payment."
        ),
        "requirements": (
            "- Track inventory per product slot\n"
            "- Accept payment, compute change, and dispense product\n"
            "- Handle insufficient payment and out-of-stock cases\n"
            "- Support cancelling a transaction and refunding inserted money"
        ),
        "constraints": (
            "- The machine has limited change denominations\n"
            "- Should be easy to add a new payment method later (e.g. card)\n"
            "- Model the machine's states explicitly (idle, selecting, paying, dispensing)"
        ),
    },
]


def seed_problems(db: Session) -> None:
    if db.query(Problem).count() > 0:
        return  # already seeded
    for p in PROBLEMS:
        db.add(Problem(**p))
    db.commit()
