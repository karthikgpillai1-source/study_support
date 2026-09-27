"""End-to-end API tests: the full MVP success criteria from the spec."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.conftest import DATABASE_NOTES, SAMPLE_NOTES, auth_headers, register


# ----------------------------------------------------------------------- health
def test_short_secret_key_is_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """A weak HMAC key must not be able to sign production tokens."""
    from app.core.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "too-short")

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings()


def test_placeholder_secret_key_is_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import PLACEHOLDER_SECRET, Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", PLACEHOLDER_SECRET)

    with pytest.raises(ValidationError, match="placeholder"):
        Settings()


def test_strong_secret_key_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import MIN_SECRET_BYTES, Settings, generate_secret_key

    key = generate_secret_key()
    assert len(key.encode()) >= MIN_SECRET_BYTES

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", key)
    assert Settings().secret_key == key


def test_short_secret_key_only_warns_in_development(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from app.core.config import Settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "short")
    with caplog.at_level(logging.WARNING):
        assert Settings().secret_key == "short"
    assert any("SECRET_KEY" in record.message for record in caplog.records)


def test_comma_separated_cors_origins_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A comma-separated CORS_ORIGINS in .env must not crash the backend.

    Regression: pydantic-settings JSON-decodes list-typed fields before field
    validators run, so declaring ``cors_origins: list[str]`` made the app fail to
    start with the default .env, and the frontend could never reach the API.
    """
    monkeypatch.setenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://study.app"
    )
    from app.core.config import Settings

    reloaded = Settings()
    assert reloaded.cors_origin_list == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://study.app",
    ]


def test_cors_origin_list_never_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "  ,  ")
    assert Settings().cors_origin_list == ["http://localhost:5173"]


def test_health_reports_the_planner_rules(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["planner_rules"]["max_daily_minutes"] == 240
    assert body["planner_rules"]["block_minutes"] == [10, 30]
    assert body["planner_rules"]["max_package_minutes"] == 90
    assert body["planner_rules"]["llm_used"] is False
    assert set(body["supported_uploads"]) >= {".pdf", ".docx", ".txt"}


# -------------------------------------------------------------------------- auth
def test_register_login_and_profile(client: TestClient) -> None:
    created = client.post(
        "/api/auth/register",
        json={
            "email": "New.Student@Example.com",
            "full_name": "New Student",
            "password": "correcthorsebattery",
        },
    )
    assert created.status_code == 201
    assert created.json()["user"]["email"] == "new.student@example.com"

    token = created.json()["access_token"]
    me = client.get("/api/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["full_name"] == "New Student"

    duplicate = client.post(
        "/api/auth/register",
        json={
            "email": "new.student@example.com",
            "full_name": "Duplicate User",
            "password": "anotherpassword",
        },
    )
    assert duplicate.status_code == 409

    bad = client.post(
        "/api/auth/login", json={"email": "new.student@example.com", "password": "wrong"}
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/auth/login",
        json={"email": "new.student@example.com", "password": "correcthorsebattery"},
    )
    assert good.status_code == 200


def test_short_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "full_name": "A B", "password": "short"},
    )
    assert response.status_code == 422


def test_protected_routes_require_a_token(client: TestClient) -> None:
    for path in ("/api/dashboard", "/api/subjects", "/api/auth/me"):
        assert client.get(path).status_code == 401
    assert (
        client.get("/api/subjects", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    )


# ------------------------------------------------------------------- solo flow
def test_full_solo_flow_upload_to_progress(
    client: TestClient, headers: dict, notes_file: bytes
) -> None:
    """MVP success criteria 1-5: upload, intelligence, packages, plan, progress."""
    # 1. Create a subject.
    created = client.post(
        "/api/subjects",
        headers=headers,
        json={
            "name": "Operating Systems",
            "knowledge_level": "beginner",
            "study_mode": "fast_exam",
            "exam_date": (date.today() + timedelta(days=21)).isoformat(),
            "daily_minutes": 120,
        },
    )
    assert created.status_code == 201
    subject_id = created.json()["id"]

    # 2. Upload notes.
    uploaded = client.post(
        f"/api/subjects/{subject_id}/documents",
        headers=headers,
        files={"file": ("os.txt", notes_file, "text/plain")},
        data={"analyze_now": "false", "use_llm": "false"},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["document"]["word_count"] > 500
    assert "Operating Systems" in uploaded.json()["text_preview"]

    # 3. Generate study intelligence.
    analyzed = client.post(
        f"/api/subjects/{subject_id}/analyze", headers=headers, params={"use_llm": "false"}
    )
    assert analyzed.status_code == 200
    intelligence = analyzed.json()
    assert intelligence["topic_count"] >= 4
    assert intelligence["total_minutes"] > 0
    assert len(intelligence["topics"]) == intelligence["topic_count"]
    for topic in intelligence["topics"]:
        assert topic["difficulty"] in ("easy", "medium", "hard")
        assert 5 <= topic["estimated_minutes"] <= 180
        assert topic["module_title"]

    # 4. Generate work packages.
    packages = client.post(f"/api/subjects/{subject_id}/packages", headers=headers)
    assert packages.status_code == 201
    body = packages.json()
    assert body["max_minutes_per_package"] == 90
    assert body["packages"], "expected work packages"
    for package in body["packages"]:
        assert package["total_minutes"] <= 90, f"{package['title']} exceeds the 90 min cap"
        for unit in package["units"]:
            assert 10 <= unit["minutes"] <= 30
    assert any(p["type"] == "study" for p in body["packages"])
    assert any(p["type"] == "revision" for p in body["packages"])

    # 5. Generate a study plan.
    plan = client.post(
        f"/api/subjects/{subject_id}/plan", headers=headers, json={"horizon_days": 14}
    )
    assert plan.status_code == 201
    plan_body = plan.json()
    assert plan_body["planned_minutes"] > 0
    assert len(plan_body["days"]) == 14
    for day in plan_body["days"]:
        assert day["planned_minutes"] <= 120  # subject budget, under the 240 cap
        for block in day["blocks"]:
            assert block["minutes"] <= 30
            if not block["is_break"]:
                assert 10 <= block["minutes"] <= 30

    # 6. Track progress.
    topic_id = intelligence["topics"][0]["id"]
    progressed = client.post(
        "/api/progress",
        headers=headers,
        json={"topic_id": topic_id, "event": "completed", "minutes_spent": 25, "confidence": 0.8},
    )
    assert progressed.status_code == 200
    assert progressed.json()["topics_completed"] == 1
    assert progressed.json()["progress_percent"] > 0

    # 7. Dashboard reflects everything.
    dashboard = client.get("/api/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["totals"]["subjects"] == 1
    assert dashboard.json()["subjects"][0]["progress_percent"] > 0
    assert len(dashboard.json()["upcoming_deadlines"]) == 1


def test_analysis_screen_returns_everything_at_once(
    client: TestClient, headers: dict, analysed_subject: dict
) -> None:
    response = client.get(f"/api/subjects/{analysed_subject['id']}/analysis", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["intelligence"] is not None
    assert body["estimates"]["grand_total_minutes"] > 0
    assert body["estimates"]["breakdown"]["easy"] >= 0
    assert body["estimates"]["days_required"] > 0
    assert "feasible" in body["estimates"]
    assert body["subject"]["has_intelligence"] is True


def test_upload_rejects_unsupported_types(client: TestClient, headers: dict, subject: dict) -> None:
    response = client.post(
        f"/api/subjects/{subject['id']}/documents",
        headers=headers,
        files={"file": ("slides.pptx", b"not a presentation", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_rejects_empty_file(client: TestClient, headers: dict, subject: dict) -> None:
    response = client.post(
        f"/api/subjects/{subject['id']}/documents",
        headers=headers,
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400


def test_docx_upload_flow(client: TestClient, headers: dict, subject: dict) -> None:
    docx = __import__("pytest").importorskip("docx")
    document = docx.Document()
    document.add_heading("Thermodynamics", level=1)
    document.add_paragraph(
        "The first law of thermodynamics states that energy is conserved. "
        "Entropy is defined as a measure of the number of microstates. "
        "An isothermal process keeps temperature constant while heat is transferred."
    )
    import io

    buffer = io.BytesIO()
    document.save(buffer)

    response = client.post(
        f"/api/subjects/{subject['id']}/documents",
        headers=headers,
        files={
            "file": (
                "thermo.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"analyze_now": "true", "use_llm": "false"},
    )
    assert response.status_code == 201
    assert response.json()["document"]["extractor"] == "python-docx"

    intelligence = client.get(f"/api/subjects/{subject['id']}/intelligence", headers=headers)
    assert intelligence.status_code == 200
    assert intelligence.json()["topic_count"] >= 1


def test_pdf_upload_flow(client: TestClient, headers: dict, subject: dict) -> None:
    pymupdf = __import__("pytest").importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 70), "Linear Algebra: Vector Spaces")
    page.insert_text((60, 90), "A vector space is defined as a set closed under addition.")
    page.insert_text((60, 110), "A basis spans the space and every basis is linearly independent.")
    data = doc.tobytes()
    doc.close()

    response = client.post(
        f"/api/subjects/{subject['id']}/documents",
        headers=headers,
        files={"file": ("linear_algebra.pdf", data, "application/pdf")},
        data={"analyze_now": "true", "use_llm": "false"},
    )
    assert response.status_code == 201
    assert response.json()["document"]["extractor"] == "pymupdf"
    assert response.json()["document"]["page_count"] == 1


def test_analysis_requires_a_document(client: TestClient, headers: dict) -> None:
    created = client.post("/api/subjects", headers=headers, json={"name": "Empty Subject"})
    subject_id = created.json()["id"]
    response = client.post(f"/api/subjects/{subject_id}/analyze", headers=headers)
    assert response.status_code == 400
    assert "Upload at least one" in response.json()["detail"]


def test_packages_require_analysis(client: TestClient, headers: dict, subject: dict) -> None:
    response = client.post(f"/api/subjects/{subject['id']}/packages", headers=headers)
    assert response.status_code == 400
    assert "analysis" in response.json()["detail"].lower()


def test_plan_requires_packages(client: TestClient, headers: dict, analysed_subject: dict) -> None:
    response = client.post(f"/api/subjects/{analysed_subject['id']}/plan", headers=headers, json={})
    assert response.status_code == 400
    assert "work packages" in response.json()["detail"].lower()


def test_planner_never_uses_an_llm(
    client: TestClient, headers: dict, packaged_subject: dict
) -> None:
    """A study plan must be byte-identical across runs with no API key set."""
    first = client.post(
        f"/api/subjects/{packaged_subject['id']}/plan", headers=headers, json={"horizon_days": 14}
    )
    signature = [
        (d["day"], [(b["start_time"], b["minutes"], b["kind"]) for b in d["blocks"]])
        for d in first.json()["days"]
    ]
    second = client.post(
        f"/api/subjects/{packaged_subject['id']}/plan", headers=headers, json={"horizon_days": 14}
    )
    repeat = [
        (d["day"], [(b["start_time"], b["minutes"], b["kind"]) for b in d["blocks"]])
        for d in second.json()["days"]
    ]
    assert signature == repeat


def test_week_summary_and_availability(
    client: TestClient, headers: dict, planned_subject: dict
) -> None:
    subject_id = planned_subject["id"]
    week = client.get(f"/api/subjects/{subject_id}/plan/week", headers=headers)
    assert week.status_code == 200
    assert week.json()["blocks_total"] > 0
    assert len(week.json()["by_day"]) == 7
    assert any(k["kind"] != "break" for k in week.json()["by_kind"])

    updated = client.patch(
        f"/api/subjects/{subject_id}/availability",
        headers=headers,
        json={"daily_minutes": 60, "start_time": "07:30", "rest_days": [7]},
    )
    assert updated.status_code == 200
    assert updated.json()["daily_minutes"] == 60

    replanned = client.get(f"/api/subjects/{subject_id}/plan/replan", headers=headers)
    assert replanned.status_code == 200
    for day in replanned.json()["days"]:
        assert day["planned_minutes"] <= 60


def test_block_completion_updates_progress(
    client: TestClient, headers: dict, planned_subject: dict
) -> None:
    plan = client.get(f"/api/subjects/{planned_subject['id']}/plan", headers=headers).json()
    block = next(b for d in plan["days"] for b in d["blocks"] if not b["is_break"])
    assert block["status"] == "planned"

    updated = client.patch(
        f"/api/blocks/{block['id']}",
        headers=headers,
        json={"status": "done", "actual_minutes": block["minutes"]},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"
    assert updated.json()["completed_at"] is not None


def test_adaptive_review_after_falling_behind(
    client: TestClient, headers: dict, planned_subject: dict
) -> None:
    subject_id = planned_subject["id"]
    plan = client.get(f"/api/subjects/{subject_id}/plan", headers=headers).json()
    block = next(b for d in plan["days"] for b in d["blocks"] if not b["is_break"])
    client.patch(
        f"/api/blocks/{block['id']}",
        headers=headers,
        json={"status": "missed", "actual_minutes": 0},
    )
    review = client.get(f"/api/subjects/{subject_id}/plan/adaptive", headers=headers)
    assert review.status_code == 200
    body = review.json()
    assert body["status"] in ("behind", "on_track", "ahead")
    assert "remaining_minutes" in body


def test_switching_study_mode_replans(
    client: TestClient, headers: dict, planned_subject: dict
) -> None:
    response = client.post(
        f"/api/subjects/{planned_subject['id']}/plan/mode?mode=college_pace", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["study_mode"] == "college_pace"
    assert response.json()["meta"]["revision_offsets_days"] == [3, 10, 21]


def test_sessions_are_recorded(client: TestClient, headers: dict, planned_subject: dict) -> None:
    started = client.post(
        "/api/sessions",
        headers=headers,
        json={"subject_id": planned_subject["id"], "notes": "evening revision"},
    )
    assert started.status_code == 201
    session_id = started.json()["id"]

    ended = client.patch(
        f"/api/sessions/{session_id}?actual_minutes=45&focus_score=0.8", headers=headers
    )
    assert ended.status_code == 200
    assert ended.json()["actual_minutes"] == 45
    assert ended.json()["ended_at"] is not None

    listed = client.get("/api/sessions", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_rest_days_are_respected_end_to_end(
    client: TestClient, headers: dict, packaged_subject: dict
) -> None:
    subject_id = packaged_subject["id"]
    client.patch(
        f"/api/subjects/{subject_id}",
        headers=headers,
        json={"daily_minutes": 240, "rest_days": [6, 7]},
    )
    plan = client.post(
        f"/api/subjects/{subject_id}/plan", headers=headers, json={"horizon_days": 14}
    ).json()
    weekend = [d for d in plan["days"] if d["day"] in (0, 6)]  # date objects, not weekdays
    del weekend
    for day in plan["days"]:
        parsed = date.fromisoformat(str(day["day"]))
        if parsed.isoweekday() in (6, 7):
            assert day["planned_minutes"] == 0, f"{parsed} was a rest day but had work"


# ------------------------------------------------------------------- team flow
def _team_setup(client: TestClient, owner_token: str, notes_file: bytes) -> dict:
    team = client.post(
        "/api/teams", headers=auth_headers(owner_token), json={"name": "CS Study Group"}
    )
    assert team.status_code == 201
    return team.json()


def test_full_team_flow_share_distribute_and_view(
    client: TestClient, headers: dict, notes_file: bytes
) -> None:
    """MVP success criteria 6-8: shared notes, distribution suggestions, shared plan."""
    team = _team_setup(client, headers["Authorization"].split()[1], notes_file)
    code = team["join_code"]
    assert [m["role"] for m in team["members"]] == ["owner"]
    assert team["owner_id"] == team["members"][0]["user_id"]

    # Invite a second member.
    member = register(client, "teammate@example.com", "Teammate")
    joined = client.post(
        "/api/teams/join", headers=auth_headers(member["access_token"]), json={"join_code": code}
    )
    assert joined.status_code == 200
    assert len(joined.json()["members"]) == 2
    team = joined.json()

    # A shared subject.
    shared = client.post(
        "/api/subjects",
        headers=headers,
        json={"name": "Algorithms", "team_id": team["id"], "daily_minutes": 90},
    )
    assert shared.status_code == 201
    subject_id = shared.json()["id"]

    # Shared notes: two units so the module-aware topic split has something to
    # partition, which is what a real shared syllabus looks like.
    uploaded = client.post(
        f"/api/subjects/{subject_id}/documents",
        headers=headers,
        files={"file": ("shared.txt", notes_file, "text/plain")},
        data={"analyze_now": "false", "use_llm": "false"},
    )
    assert uploaded.status_code == 201
    second = client.post(
        f"/api/subjects/{subject_id}/documents",
        headers=headers,
        files={"file": ("databases.txt", DATABASE_NOTES, "text/plain")},
        data={"analyze_now": "false", "use_llm": "false"},
    )
    assert second.status_code == 201

    # Both members can see the shared subject and run the same analysis.
    for token in (headers["Authorization"].split()[1], member["access_token"]):
        response = client.post(
            f"/api/subjects/{subject_id}/analyze",
            headers=auth_headers(token),
            params={"use_llm": "false"},
        )
        assert response.status_code == 200

    packages = client.post(f"/api/subjects/{subject_id}/packages", headers=headers)
    assert packages.status_code == 201
    intelligence = client.get(f"/api/subjects/{subject_id}/intelligence", headers=headers).json()

    # Distribution suggestions: all five strategies, nothing applied yet.
    split = client.get(f"/api/subjects/{subject_id}/split", headers=headers)
    assert split.status_code == 200
    suggestions = split.json()["suggestions"]
    assert {s["strategy"] for s in suggestions} == {
        "topic",
        "difficulty",
        "time",
        "teaching",
        "revision",
    }
    study_packages = [p for p in packages.json()["packages"] if p["type"] == "study"]
    revision_packages = [p for p in packages.json()["packages"] if p["type"] == "revision"]
    expected = {
        "topic": {p["id"] for p in study_packages},
        "difficulty": {p["id"] for p in study_packages},
        "time": {p["id"] for p in study_packages},
        "teaching": {p["id"] for p in study_packages},
        "revision": {p["id"] for p in revision_packages},
    }

    for suggestion in suggestions:
        assert suggestion["rationale"]
        assert suggestion["total_minutes"] > 0
        ids = {a["user_id"] for a in suggestion["assignments"]}
        assert ids == {team["members"][0]["user_id"], team["members"][1]["user_id"]}

        # Every relevant package is owned by exactly one member: none dropped,
        # none double-assigned.
        assigned = [pid for a in suggestion["assignments"] for pid in a["package_ids"]]
        assert sorted(assigned) == sorted(expected[suggestion["strategy"]]), (
            f"{suggestion['strategy']} did not partition its packages exactly once"
        )
        assert len(assigned) == len(set(assigned))

        # Minutes and difficulty counts must agree with the packages held.
        minutes_by_id = {p["id"]: p["total_minutes"] for p in packages.json()["packages"]}
        for a in suggestion["assignments"]:
            assert a["minutes"] == sum(minutes_by_id[pid] for pid in a["package_ids"])
            assert sum(a["difficulty_load"].values()) == len(a["package_ids"])

    by_strategy = {s["strategy"]: s for s in suggestions}
    all_packages = packages.json()["packages"]
    minutes_by_id = {p["id"]: p["total_minutes"] for p in all_packages}

    # time split: levelled within the best bound achievable for indivisible
    # packages (longest-processing-time-first guarantees max load <= ideal + largest).
    time_loads = [a["minutes"] for a in by_strategy["time"]["assignments"]]
    if all(time_loads):
        ideal = sum(time_loads) / len(time_loads)
        largest = max(minutes_by_id[pid] for pid in expected["time"])
        assert max(time_loads) <= ideal + largest + 1, f"time split unbalanced: {time_loads}"

    # topic split: modules stay whole unless there were fewer modules than members,
    # in which case the largest one is opened up so nobody sits idle.
    package_module = {
        p["id"]: next(
            (t["module_title"] for t in intelligence["topics"] if t["id"] in p["topic_ids"]),
            "General",
        )
        for p in packages.json()["packages"]
    }
    module_count = len({package_module[pid] for pid in expected["topic"]})
    topic_assignments = by_strategy["topic"]["assignments"]
    assert all(a["package_ids"] for a in topic_assignments), "someone was left with no work"
    if module_count >= 2:
        for a in topic_assignments:
            modules = [package_module[pid] for pid in a["package_ids"]]
            # At most one module may be shared, and only when modules are scarce.
            duplicated = len(modules) - len(set(modules))
            assert duplicated <= 1, f"topic split fragmented too much: {modules}"

    # difficulty split: the easy/medium/hard spread is levelled.
    for band in ("easy", "medium", "hard"):
        counts = [a["difficulty_load"][band] for a in by_strategy["difficulty"]["assignments"]]
        assert max(counts) - min(counts) <= 1, f"{band} band unbalanced: {counts}"

    # revision split touches revision packages only.
    assert all(
        pid in {p["id"] for p in revision_packages}
        for a in by_strategy["revision"]["assignments"]
        for pid in a["package_ids"]
    )
    assert any(a["revision_topic_ids"] for a in by_strategy["revision"]["assignments"])

    # teaching split: study-package base plus at least one suggested presenter.
    teaching_ids = {p["id"] for p in study_packages}
    teaching_assignments = by_strategy["teaching"]["assignments"]
    assert set(pid for a in teaching_assignments for pid in a["package_ids"]) <= teaching_ids
    assert any(a["teaching_topics"] for a in teaching_assignments)

    # Suggestions are inert until explicitly accepted.
    before = client.get(f"/api/subjects/{subject_id}/ownership", headers=headers).json()
    assert before == []

    accepted = next(s for s in suggestions if s["strategy"] == "time")
    applied = client.post(
        f"/api/subjects/{subject_id}/split/apply",
        headers=headers,
        json={"strategy": "time", "assignments": accepted["assignments"]},
    )
    assert applied.status_code == 200
    assert applied.json()["assignments_applied"] > 0

    ownership = client.get(f"/api/subjects/{subject_id}/ownership", headers=headers).json()
    assert ownership
    assert {row["strategy"] for row in ownership} == {"time"}

    # Shared study plan: both members see the same plan.
    plan = client.post(
        f"/api/subjects/{subject_id}/plan", headers=headers, json={"horizon_days": 10}
    )
    assert plan.status_code == 201
    shared_view = client.get(
        f"/api/subjects/{subject_id}/plan", headers=auth_headers(member["access_token"])
    )
    assert shared_view.status_code == 200
    assert shared_view.json()["planned_minutes"] == plan.json()["planned_minutes"]

    # Knowledge matrix is shared.
    matrix = client.get(f"/api/subjects/{subject_id}/matrix", headers=headers)
    assert matrix.status_code == 200
    assert len(matrix.json()["members"]) == 2
    assert matrix.json()["topic_ids"]

    # Peer recommendations are advisory only.
    peers = client.get(f"/api/subjects/{subject_id}/peers", headers=headers)
    assert peers.status_code == 200
    assert "Nothing is assigned automatically" in peers.json()["note"]


def test_knowledge_matrix_reflects_individual_progress(
    client: TestClient, headers: dict, packaged_subject: dict
) -> None:
    team = _team_setup(client, headers["Authorization"].split()[1], b"")
    member = register(client, "matrix@example.com", "Matrix Member")
    client.post(
        "/api/teams/join",
        headers=auth_headers(member["access_token"]),
        json={"join_code": team["join_code"]},
    )
    shared = client.post(
        "/api/subjects",
        headers=headers,
        json={"name": "Shared OS", "team_id": team["id"]},
    ).json()

    # Copy intelligence and packages across so both members share the same topics.
    client.post(
        f"/api/subjects/{shared['id']}/documents",
        headers=headers,
        files={"file": ("os.txt", SAMPLE_NOTES.encode(), "text/plain")},
        data={"analyze_now": "true", "use_llm": "false"},
    )
    client.post(f"/api/subjects/{shared['id']}/packages", headers=headers)

    intelligence = client.get(f"/api/subjects/{shared['id']}/intelligence", headers=headers).json()
    topic_id = intelligence["topics"][0]["id"]

    # One member masters a topic.
    client.post(
        "/api/progress",
        headers=headers,
        json={"topic_id": topic_id, "event": "completed", "minutes_spent": 30, "confidence": 1.0},
    )
    client.post(
        f"/api/subjects/{shared['id']}/peers/signal",
        headers=headers,
        params={"topic_id": topic_id, "kind": "mastered"},
    )

    matrix = client.get(f"/api/subjects/{shared['id']}/matrix", headers=headers).json()
    rows = {row["user_id"]: row for row in matrix["members"]}
    expert = rows[1]  # the owner, who recorded progress
    learner = rows[2]  # the teammate, who did not
    owner_cell = next(c for c in expert["cells"] if c["topic_id"] == topic_id)
    learner_cell = next(c for c in learner["cells"] if c["topic_id"] == topic_id)
    assert owner_cell["mastery"] > learner_cell["mastery"]
    assert expert["strong_count"] >= 1

    peers = client.get(f"/api/subjects/{shared['id']}/peers", headers=headers).json()
    expert_profiles = [e for e in peers["experts"] if e["user_id"] == 1]
    assert expert_profiles, "expected the member who recorded progress to be ranked as an expert"
    assert (
        topic_id
        in expert_profiles[0]["expert_topic_ids"] + expert_profiles[0]["near_expert_topic_ids"]
    )


def test_outside_users_cannot_see_a_private_subject(
    client: TestClient, headers: dict, subject: dict
) -> None:
    stranger = register(client, "stranger@example.com", "Stranger")
    other = auth_headers(stranger["access_token"])
    assert client.get(f"/api/subjects/{subject['id']}", headers=other).status_code == 403
    assert client.get("/api/subjects", headers=other).json() == []
    assert (
        client.post(
            f"/api/subjects/{subject['id']}/analyze", headers=other, params={"use_llm": "false"}
        ).status_code
        == 403
    )


def test_only_team_leads_accept_a_distribution(
    client: TestClient, headers: dict, packaged_subject: dict
) -> None:
    team = _team_setup(client, headers["Authorization"].split()[1], b"")
    member = register(client, "member2@example.com", "Member Two")
    client.post(
        "/api/teams/join",
        headers=auth_headers(member["access_token"]),
        json={"join_code": team["join_code"]},
    )
    shared = client.post(
        "/api/subjects",
        headers=headers,
        json={"name": "Shared", "team_id": team["id"]},
    ).json()
    client.post(
        f"/api/subjects/{shared['id']}/documents",
        headers=headers,
        files={"file": ("os.txt", SAMPLE_NOTES.encode(), "text/plain")},
        data={"analyze_now": "true", "use_llm": "false"},
    )
    client.post(f"/api/subjects/{shared['id']}/packages", headers=headers)

    split = client.get(f"/api/subjects/{shared['id']}/split", headers=headers).json()
    suggestion = split["suggestions"][0]
    rejected = client.post(
        f"/api/subjects/{shared['id']}/split/apply",
        headers=auth_headers(member["access_token"]),
        json={"strategy": suggestion["strategy"], "assignments": suggestion["assignments"]},
    )
    assert rejected.status_code == 403


def test_invalid_join_code_is_rejected(client: TestClient) -> None:
    account = register(client, "lonely@example.com", "Lonely")
    response = client.post(
        "/api/teams/join",
        headers=auth_headers(account["access_token"]),
        json={"join_code": "ZZZZZZ"},
    )
    assert response.status_code == 404


def test_subject_deletion_cascades(
    client: TestClient, headers: dict, planned_subject: dict
) -> None:
    subject_id = planned_subject["id"]
    assert client.delete(f"/api/subjects/{subject_id}", headers=headers).status_code == 204
    assert client.get(f"/api/subjects/{subject_id}", headers=headers).status_code == 404
    assert client.get("/api/subjects", headers=headers).json() == []
