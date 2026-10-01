"""Web app (M2/M3) with fake providers: auth, CSRF, the full run flow, access rules."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
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
    assert "Vraag 1 · onderwerp 1 van" in page.text
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
    assert "Focus voor de volgende keer" in review.text and "you have this" not in review.text
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


def test_focus_label_is_shortened_at_a_word_boundary() -> None:
    from app.followup.focus import short

    text = (
        "Minimaal 2 jaar aantoonbare werkervaring met het gekozen profiel of soortgelijke functie."
    )
    out = short(text)
    assert out.endswith("…") and len(out) <= 61
    assert out[:-1] == text[: len(out) - 1]  # a prefix of the original
    assert text[len(out) - 1] == " "  # cut between words
    assert short("kort") == "kort"


def test_public_demo_needs_no_login_and_offers_no_run_actions(
    web: tuple[TestClient, Stack],
) -> None:
    client, _ = web
    client.cookies.clear()
    for lang, word in (("nl", "Terugblik"), ("en", "Review")):
        page = client.get(f"/demo?lang={lang}")
        assert page.status_code == 200 and word in page.text
        assert "Sanne Visser" in page.text or "Sanne" in page.text  # fictional candidate
        assert 'action="/runs/' not in page.text and "/practice/" not in page.text
        assert f'lang="{lang}"' in page.text
    pdf = client.get("/demo/report.pdf?lang=en")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")


def test_demo_reads_as_an_example_not_as_the_app(web: tuple[TestClient, Stack]) -> None:
    client, _ = web
    client.cookies.clear()
    for lang, eyebrow, tab in (
        ("nl", "Rondleiding", "Voorbeeldresultaat"),
        ("en", "Walkthrough", "Example result"),
    ):
        page = client.get(f"/demo?lang={lang}").text
        assert eyebrow in page and tab in page and 'class="example-frame"' in page
        assert "geen account nodig" not in page and "no account needed" not in page
        for n in (1, 2):  # the walkthrough screenshots exist for both languages
            src = f"/static/demo/{lang}-step{n}.png"
            assert src in page
            assert client.get(src).status_code == 200
        # no shared code configured: invitation only, no sign-up link
        assert 'id="try"' in page and "/register?code=" not in page


def test_demo_try_it_button_follows_the_laptop(web: tuple[TestClient, Stack]) -> None:
    client, st = web
    client.cookies.clear()
    settings = client.app.state.settings  # type: ignore[attr-defined]
    settings.demo_signup_code = "team-2026"
    settings.demo_contact_email = "me@example.org"
    page = client.get("/demo?lang=en").text
    assert "/register?code=team-2026" in page and "online right now" in page
    st.local.online = False  # laptop asleep: no button, and the code is not shown
    page = client.get("/demo?lang=en").text
    assert "team-2026" not in page and "offline right now" in page
    assert "mailto:me@example.org" in page
    st.local.online = True
    settings.demo_signup_max = 0  # no places left
    page = client.get("/demo?lang=en").text
    assert "team-2026" not in page and "by invitation" in page


def test_shared_signup_code_has_a_cap_and_an_end_date(engine: Engine) -> None:
    from app.web.auth import SHARED_SIGNUP, SharedSignup, register

    pw = "a-long-password"
    shared = SharedSignup("team-2026", max_users=2)
    for i in range(2):
        user = register(engine, " team-2026 ", f"p{i}@example.org", pw, shared)
        assert user.role == "candidate" and user.invited_by == SHARED_SIGNUP
    with pytest.raises(ValueError, match="no longer valid"):
        register(engine, "team-2026", "p3@example.org", pw, shared)
    with pytest.raises(ValueError, match="already exists"):
        register(engine, "team-2026", "p0@example.org", pw, SharedSignup("team-2026", 9))
    past = SharedSignup("team-2026", 9, until=date.today() - timedelta(days=1))
    assert not past.is_open(engine)
    with pytest.raises(ValueError, match="no longer valid"):
        register(engine, "team-2026", "p4@example.org", pw, past)
    # an unset shared code never matches; other codes still go through the invites table
    with pytest.raises(ValueError, match="invite code is not valid"):
        register(engine, "", "p5@example.org", pw, SharedSignup("", 9))
    with pytest.raises(ValueError, match="invite code is not valid"):
        register(engine, "team-2027", "p6@example.org", pw, shared)


def test_download_is_named_after_the_vacancy() -> None:
    from app.web.routes import download_header

    assert download_header("AI Engineer", "pdf") == (
        "attachment; filename=\"AI Engineer.pdf\"; filename*=UTF-8''AI%20Engineer.pdf"
    )
    # unsafe characters removed, non-ASCII kept in filename* with an ASCII fallback
    h = download_header('Data/AI "Specialist": Ré', "json")
    assert 'filename="Data AI Specialist Re.json"' in h
    assert "filename*=UTF-8''Data%20AI%20Specialist%20R%C3%A9.json" in h
    assert 'filename="Interview Coach.pdf"' in download_header("", "pdf")
    assert download_header("x", "pdf", inline=True).startswith("inline;")
