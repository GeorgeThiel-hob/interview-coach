"""Design snapshots: every page rendered with fictional data, saved as standalone HTML.

Run with ``make snapshots`` (deselected in normal test runs). Output: ``design/snapshots/``
(git-ignored), one file per screen plus the vendored JS, viewable offline in a browser and
uploadable to a design tool. See docs/design-handoff.md.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web.i18n import translate
from app.web.routes import TEMPLATES
from tests import test_web
from tests.conftest import Stack
from tests.test_e2e import weak_answers
from tests.test_web import csrf, login_new_user, new_run, wait_status

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design" / "snapshots"
VENDOR = ROOT / "app" / "static" / "vendor"

pytestmark = pytest.mark.snapshot
web = test_web.web  # reuse the web-app fixture


def save(name: str, html: str) -> None:
    # standalone: vendored scripts next to the file, no server needed
    html = html.replace('src="/static/', 'src="static/')
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")


def page(client: TestClient, path: str) -> str:
    r = client.get(path, follow_redirects=True)
    assert r.status_code == 200, (path, r.status_code)
    return r.text


def test_snapshot_all_pages(web: tuple[TestClient, Stack]) -> None:
    client, st = web
    st.jev.handlers["judge"] = weak_answers
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "static").mkdir(parents=True)
    shutil.copytree(VENDOR, OUT / "static" / "vendor")

    save("01-login", page(client, "/login"))
    login_new_user(client, st, "jan@example.nl")
    save("03-home-empty", page(client, "/"))
    save("04-new-run", page(client, "/runs/new"))

    run_id = new_run(client)
    wait_status(st, run_id, "ready")
    save("06-briefing", page(client, f"/runs/{run_id}/briefing"))
    save("07-interview-question", page(client, f"/runs/{run_id}/interview"))

    token = csrf(client, f"/runs/{run_id}/interview")
    follow_up_saved = False
    for n in range(40):
        r = client.post(
            f"/runs/{run_id}/answer",
            headers={"X-CSRF-Token": token, "HX-Request": "true"},
            data={"text": f"Bij ACME bouwde ik met Petra Jansen een pipeline ({n})."},
        )
        assert r.status_code == 200, r.text
        if "hx-get" in r.text:  # finished partial
            break
        if not follow_up_saved and "vervolgvraag" in r.text:
            save("08-interview-follow-up", page(client, f"/runs/{run_id}/interview"))
            follow_up_saved = True
    wait_status(st, run_id, "done")

    review = page(client, f"/runs/{run_id}/review")
    save("10-review", review)
    turn = re.search(r'/practice/([0-9a-f]+)"', review)
    assert turn
    save("11-practice-question", page(client, f"/runs/{run_id}/practice/{turn.group(1)}"))
    save("12-home-with-runs", page(client, "/"))
    save("13-tips", page(client, "/tips"))

    # admin view: log in as the admin the helper created
    client.cookies.clear()
    token = csrf(client, "/login")
    r = client.post(
        "/login",
        data={"csrf": token, "email": "admin-jan@example.nl", "password": "x" * 12},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    save("14-admin", page(client, "/admin"))

    # screens that are hard to reach with instant fake models: render their templates directly
    t = lambda key: translate(key, "nl")  # noqa: E731
    base = {"t": t, "lang": "nl", "csrf": "x", "user": {"role": "candidate"}, "request": None}

    class RunStub:
        id = run_id
        error = None

        def __init__(self, status: str) -> None:
            self.status = status

    status_page = TEMPLATES.env.get_template("run_status.html")
    save(
        "05-preparing",
        status_page.render(
            run=RunStub("preparing"),
            messages=["reading vacancy", "reading cv", "extracting requirements"],
            **base,
        ),
    )
    save(
        "09-writing-review",
        status_page.render(
            run=RunStub("reviewing"), messages=["writing feedback per answer"], **base
        ),
    )
    for name, template, ctx in [
        ("02-register", "register.html", {"code": "ABCD-1234", "user": None}),
        ("16-error", "error.html", {"message": "Voorbeeld van een foutmelding."}),
    ]:
        save(name, TEMPLATES.env.get_template(template).render(**{**base, **ctx}))
    offline = TEMPLATES.env.from_string(
        "{% extends 'base.html' %}{% block content %}"
        "<div id='turn'>{% include 'partials/offline.html' %}</div>{% endblock %}"
    )
    save("15-local-model-offline", offline.render(**base))
