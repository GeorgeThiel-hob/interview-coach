"""Web app (M2/M3) with fake providers: auth, CSRF, the full run flow, access rules."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import Run
from app.main import create_app
from app.settings import Settings
from app.web.auth import create_invite, create_user
from tests.conftest import CV, VACANCY, Stack
from tests.test_e2e import weak_answers


class FakeTranscriber:
    def transcribe(self, audio_path: Path, language: str) -> str:
        return "Ik bouwde eh een pipeline met Petra Jansen."


@pytest.fixture
def web(stack: Stack, tmp_path: Path) -> Iterator[tuple[TestClient, Stack]]:
    settings = Settings(
        session_secret="s" * 40,
        pii_encryption_key=stack.key,
        secure_cookies=False,
        data_dir=tmp_path,
        runs_per_user_per_day=50,
    )
    app = create_app(settings, gateway=stack.gateway, engine=stack.engine)
    with TestClient(app) as client:
        app.state.transcriber = FakeTranscriber()
        yield client, stack


def csrf(client: TestClient, path: str = "/login") -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, html[:500]
    return match.group(1)


def login_new_user(client: TestClient, st: Stack, email: str) -> None:
    admin = create_user(st.engine, f"admin-{email}", "x" * 12, role="admin")
    code = create_invite(st.engine, admin.id)
    client.cookies.clear()
    token = csrf(client, f"/register?code={code}")
    r = client.post(
        "/register",
        data={"csrf": token, "code": code, "email": email, "password": "a-long-password"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def wait_status(st: Stack, run_id: str, want: str, timeout: float = 20) -> Run:
    end = time.time() + timeout
    while time.time() < end:
        with Session(st.engine) as s:
            run = s.get(Run, run_id)
        if run and run.status == want:
            return run
        if run and run.status == "failed":
            raise AssertionError(run.error)
        time.sleep(0.05)
    raise AssertionError(f"run stayed {run.status if run else None}")


def new_run(client: TestClient) -> str:
    token = csrf(client, "/runs/new")
    r = client.post(
        "/runs",
        data={
            "csrf": token,
            "language": "nl",
            "length": "15",
            "interview_type": "mixed",
            "answer_mode": "typed",
            "difficulty": "realistic",
            "vacancy_text": VACANCY,
        },
        files={"cv_file": ("cv.txt", CV.encode(), "text/plain")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return r.headers["location"].rsplit("/", 1)[1]


def test_requires_login_and_csrf(web: tuple[TestClient, Stack]) -> None:
    client, _ = web
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    r = client.post("/login", data={"email": "a@b.c", "password": "x"})
    assert r.status_code == 403  # no CSRF token


def test_full_web_flow(web: tuple[TestClient, Stack]) -> None:
    client, st = web
    st.jev.handlers["judge"] = weak_answers
    login_new_user(client, st, "cand@example.nl")
    run_id = new_run(client)
    wait_status(st, run_id, "ready")

    briefing = client.get(f"/runs/{run_id}", follow_redirects=True)
    assert "Briefing" in briefing.text

    page = client.get(f"/runs/{run_id}/interview")
    assert page.status_code == 200 and 'class="question"' in page.text
    token = csrf(client, f"/runs/{run_id}/interview")
    for n in range(40):
        r = client.post(
            f"/runs/{run_id}/answer",
            headers={"X-CSRF-Token": token, "HX-Request": "true"},
            data={"text": f"Met Petra Jansen bouwde ik pipeline {n}."},
        )
        assert r.status_code == 200, r.text
        if "hx-get" in r.text:  # the finished partial
            break
    wait_status(st, run_id, "done")

    review = client.get(f"/runs/{run_id}/review")
    assert review.status_code == 200
    assert "Petra Jansen" in review.text  # real names restored for the owner only
    assert "badge" in review.text and "starChart" in review.text
    assert client.get(f"/runs/{run_id}/report.pdf").content.startswith(b"%PDF-")
    assert '"schema": "report/v1"' in client.get(f"/runs/{run_id}/report.json").text

    # practise a question again: typed and via the (fake) transcriber
    answer_id = re.search(r'/practice/([0-9a-f]+)"', review.text).group(1)  # type: ignore[union-attr]
    t = client.post(
        f"/runs/{run_id}/transcribe",
        headers={"X-CSRF-Token": token},
        files={"audio": ("a.webm", b"\x1aE\xdf\xa3" + b"0" * 100, "audio/webm")},
        data={"duration_s": "12"},
    )
    assert t.json()["text"].startswith("Ik bouwde")
    r = client.post(
        f"/runs/{run_id}/practice/{answer_id}",
        headers={"X-CSRF-Token": token},
        data={"text": t.json()["text"], "audio_duration_s": "12"},
    )
    assert r.status_code == 200 and "Na #1" in r.text and "wpm" in r.text

    # another candidate and the admin cannot open this run
    login_new_user(client, st, "other@example.nl")
    assert client.get(f"/runs/{run_id}/review").status_code == 404
    admin = create_user(st.engine, "boss@example.nl", "b" * 12, role="admin")
    client.cookies.clear()
    tok = csrf(client)
    client.post("/login", data={"csrf": tok, "email": admin.email, "password": "b" * 12})
    assert client.get(f"/runs/{run_id}/review").status_code == 404
    admin_page = client.get("/admin")
    assert admin_page.status_code == 200 and "Petra" not in admin_page.text
    assert "handled locally" in admin_page.text


def test_new_runs_blocked_when_laptop_offline(web: tuple[TestClient, Stack]) -> None:
    client, st = web
    login_new_user(client, st, "c2@example.nl")
    st.local.online = False
    token = csrf(client, "/runs/new")
    r = client.post(
        "/runs",
        data={"csrf": token, "vacancy_text": VACANCY},
        files={"cv_file": ("cv.txt", CV.encode(), "text/plain")},
    )
    assert r.status_code == 503
    assert client.get("/healthz").json()["new_runs_allowed"] is False


def test_bad_upload_shows_clear_error(web: tuple[TestClient, Stack]) -> None:
    client, st = web
    login_new_user(client, st, "c3@example.nl")
    token = csrf(client, "/runs/new")
    r = client.post(
        "/runs",
        data={"csrf": token, "vacancy_text": VACANCY},
        files={"cv_file": ("cv.exe", b"MZ\x90\x00binary", "application/octet-stream")},
    )
    assert r.status_code == 400 and "Unsupported file type" in r.text


def test_login_rate_limit(web: tuple[TestClient, Stack]) -> None:
    client, _ = web
    token = csrf(client)
    codes = [
        client.post(
            "/login", data={"csrf": token, "email": "x@y.z", "password": "nope"}
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [400] * 5 and codes[5] == 429
