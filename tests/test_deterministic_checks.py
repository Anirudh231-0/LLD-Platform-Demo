from app.services.evaluator import run_deterministic_checks


def test_rejects_too_short_submission():
    result = run_deterministic_checks("too short")
    assert result.passed is False
    assert "short" in result.reason.lower()


def test_rejects_submission_with_no_structure_hints():
    # Long enough, but doesn't mention any class/object/responsibility language.
    content = "I think about parking a lot and it should be pretty simple to figure out honestly. " * 2
    result = run_deterministic_checks(content)
    assert result.passed is False
    assert "class" in result.reason.lower() or "responsibilit" in result.reason.lower()


def test_accepts_reasonable_submission():
    content = """
    class ParkingSpot:
        responsibility: track occupancy and size
    class Vehicle:
        responsibility: know its own size/type
    ParkingLot is responsible for assigning a Vehicle to the smallest fitting ParkingSpot.
    """
    result = run_deterministic_checks(content)
    assert result.passed is True
    assert result.reason is None
