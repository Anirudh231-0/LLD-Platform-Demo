from app.services.evaluator import EvaluationResult, FeedbackItemResult


class _FakeEvaluator:
    name = "fake-for-api-tests"

    def evaluate(self, problem_prompt, requirements, submission_content):
        return EvaluationResult(
            overall_summary="Decent attempt.",
            items=[
                FeedbackItemResult(
                    criterion="class_responsibilities",
                    score=3,
                    evidence="submission text",
                    concern="Could split responsibilities further.",
                    suggestion="Consider a separate PaymentProcessor class.",
                )
            ],
            evaluator_name=self.name,
        )


def test_full_practice_loop(client, monkeypatch):
    import app.routers.attempts as attempts_module

    monkeypatch.setattr(attempts_module, "get_default_evaluator", lambda: _FakeEvaluator())

    # 1. List problems (should be seeded on startup)
    res = client.get("/api/problems")
    assert res.status_code == 200
    problems = res.json()
    assert len(problems) == 3
    problem_id = problems[0]["id"]

    # 2. Start an attempt
    res = client.post("/api/attempts", json={"problem_id": problem_id})
    assert res.status_code == 200
    attempt = res.json()
    attempt_id = attempt["id"]

    # 3. Submit a solution
    content = "class ParkingLot: responsibility is assigning ParkingSpot to Vehicle by size."
    res = client.post(f"/api/attempts/{attempt_id}/submissions", json={"content": content})
    assert res.status_code == 200
    submission = res.json()
    assert submission["version"] == 1

    # 4. Evaluation should complete (TestClient runs BackgroundTasks synchronously)
    res = client.get(f"/api/attempts/{attempt_id}/submissions/{submission['id']}/evaluation")
    assert res.status_code == 200
    evaluation = res.json()
    assert evaluation["status"] == "COMPLETED"
    assert len(evaluation["feedback_items"]) == 1

    # 5. History should reflect the attempt
    res = client.get("/api/history")
    assert res.status_code == 200
    history = res.json()
    assert len(history) == 1
    assert history[0]["latest_evaluation"]["status"] == "COMPLETED"


def test_duplicate_submission_is_idempotent(client, monkeypatch):
    import app.routers.attempts as attempts_module

    monkeypatch.setattr(attempts_module, "get_default_evaluator", lambda: _FakeEvaluator())

    res = client.get("/api/problems")
    problem_id = res.json()[0]["id"]
    res = client.post("/api/attempts", json={"problem_id": problem_id})
    attempt_id = res.json()["id"]

    content = "class ParkingLot: responsibility is assigning spots to vehicles by size."
    res1 = client.post(f"/api/attempts/{attempt_id}/submissions", json={"content": content})
    res2 = client.post(f"/api/attempts/{attempt_id}/submissions", json={"content": content})

    assert res1.json()["id"] == res2.json()["id"]

    res = client.get(f"/api/attempts/{attempt_id}/submissions")
    assert len(res.json()) == 1  # no duplicate row created


def test_retry_creates_new_version(client, monkeypatch):
    import app.routers.attempts as attempts_module

    monkeypatch.setattr(attempts_module, "get_default_evaluator", lambda: _FakeEvaluator())

    res = client.get("/api/problems")
    problem_id = res.json()[0]["id"]
    res = client.post("/api/attempts", json={"problem_id": problem_id})
    attempt_id = res.json()["id"]

    res1 = client.post(
        f"/api/attempts/{attempt_id}/submissions",
        json={"content": "class ParkingLot: responsibility is assigning spots v1"},
    )
    res2 = client.post(
        f"/api/attempts/{attempt_id}/submissions",
        json={"content": "class ParkingLot: responsibility is assigning spots v2 improved"},
    )

    assert res1.json()["version"] == 1
    assert res2.json()["version"] == 2
