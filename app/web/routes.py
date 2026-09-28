"""Web routes (M2/M3). Server-rendered Jinja2 + HTMX; no JS build step.

Access rules: a candidate only sees their own runs. Admins see usage metrics and invites,
never run content (spec section 3).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db.models import Invite, Judgment, PlanTopic, Requirement, Run, Turn, User
from app.ingest.parse import ParsedFile, UploadError, parse_pasted, parse_upload
from app.ingest.pseudonymise import pseudonymise
from app.ingest.service import load_mapping
from app.interview.engine import InterviewEngine
from app.interview.evaluation import evaluate_answer
from app.llm.errors import BudgetExceeded, LocalModelOffline, ProviderError
from app.pipeline import add_document, create_run, finish, prepare, set_status
from app.report.build import build_report, judgment_key, qa_pairs
from app.report.export import ReportImportError, load_report, to_pdf
from app.report.schema import Report
from app.review.metrics import speaking_stats
from app.review.tips import all_tips
from app.review.usage import usage
from app.web.auth import (
    authenticate,
    check_csrf,
    create_invite,
    csrf_token,
    current_user,
    login_allowed,
    record_failed_login,
    register,
)
from app.web.i18n import translate

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
router = APIRouter(dependencies=[Depends(check_csrf)])


# ---------------------------------------------------------------- helpers


def lang_of(request: Request) -> str:
    q = request.query_params.get("lang")
    if q in ("nl", "en"):
        request.session["lang"] = q
    return str(request.session.get("lang", "nl"))


def speech_available(request: Request) -> bool:
    """Spoken answers need faster-whisper in the image (WITH_SPEECH=1) or an injected fake."""
    import importlib.util

    return request.app.state.transcriber is not None or bool(
        importlib.util.find_spec("faster_whisper")
    )


def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    lang = lang_of(request)
    run = ctx.get("run")
    if isinstance(run, Run) and run.settings.get("language") in ("nl", "en"):
        lang = str(run.settings["language"])  # pages of a run speak the interview language
    return TEMPLATES.TemplateResponse(
        request,
        name,
        {
            "t": lambda k: translate(k, lang),
            "lang": lang,
            "user": current_user(request),
            "csrf": csrf_token(request),
            "speech_ok": speech_available(request),
            **ctx,
        },
        status_code=status_code,
    )


def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request) -> User:
    user = require_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403)
    return user


def own_run(request: Request, run_id: str) -> Run:
    user = require_user(request)
    with Session(request.app.state.engine) as s:
        run = s.get(Run, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=404)
    return run


def spawn(request: Request, run_id: str, coro: Any) -> None:
    jobs: dict[str, asyncio.Task[Any]] = request.app.state.jobs
    task = asyncio.create_task(coro)
    jobs[run_id] = task


def progress(request: Request, run_id: str) -> Any:
    log_: dict[str, list[str]] = request.app.state.progress

    def say(message: str) -> None:
        log_.setdefault(run_id, []).append(message)

    return say


def engine_for(request: Request, run_id: str) -> InterviewEngine:
    cache: dict[str, InterviewEngine] = request.app.state.interviews
    if run_id not in cache:
        cache[run_id] = InterviewEngine(
            request.app.state.gateway,
            request.app.state.engine,
            run_id,
            request.app.state.settings.pii_encryption_key,
        )
    return cache[run_id]


async def read_upload(upload: UploadFile | None, max_bytes: int) -> tuple[bytes, str] | None:
    if upload is None or not upload.filename:
        return None
    data = await upload.read(max_bytes + 1)
    return data, upload.filename


# ---------------------------------------------------------------- auth


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return render(request, "login.html")


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
    key = f"{request.client.host if request.client else '?'}|{email.strip().lower()}"
    if not login_allowed(key):
        return render(request, "login.html", 429, error="Too many attempts. Wait 10 minutes.")
    user = authenticate(request.app.state.engine, email, password)
    if user is None:
        record_failed_login(key)
        return render(request, "login.html", 400, error="Wrong email or password.")
    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, code: str = "") -> HTMLResponse:
    return render(request, "register.html", code=code)


@router.post("/register")
async def register_submit(
    request: Request, code: str = Form(...), email: str = Form(...), password: str = Form(...)
) -> Response:
    try:
        user = register(request.app.state.engine, code, email, password)
    except ValueError as e:
        return render(request, "register.html", 400, error=str(e), code=code)
    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- runs


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    user = require_user(request)
    with Session(request.app.state.engine) as s:
        runs = s.exec(select(Run).where(Run.user_id == user.id)).all()
    runs = sorted(runs, key=lambda r: r.created_at, reverse=True)
    local_ok = await request.app.state.gateway.local_available()
    return render(request, "home.html", runs=runs, local_ok=local_ok)


@router.get("/runs/new", response_class=HTMLResponse)
async def new_run_page(request: Request) -> HTMLResponse:
    require_user(request)
    local_ok = await request.app.state.gateway.local_available()
    return render(request, "new_run.html", local_ok=local_ok)


def _runs_today(request: Request, user: User) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    with Session(request.app.state.engine) as s:
        runs = s.exec(select(Run).where(Run.user_id == user.id)).all()
    return sum(1 for r in runs if r.created_at.replace(tzinfo=UTC) >= since)


@router.post("/runs")
async def create_run_submit(
    request: Request,
    vacancy_file: UploadFile | None = File(None),
    vacancy_text: str = Form(""),
    cv_file: UploadFile | None = File(None),
    extra_file: UploadFile | None = File(None),
    previous_file: UploadFile | None = File(None),
    interview_type: str = Form("mixed"),
    language: str = Form("nl"),
    length: int = Form(30),
    answer_mode: str = Form("typed"),
    difficulty: str = Form("realistic"),
) -> Response:
    user = require_user(request)
    app = request.app
    settings = app.state.settings
    max_bytes = settings.max_upload_mb * 1024 * 1024

    def fail(msg: str, code: int = 400) -> HTMLResponse:
        return render(request, "new_run.html", code, error=msg, local_ok=True)

    if not await app.state.gateway.local_available():
        return fail(translate("local_offline", lang_of(request)), 503)
    if _runs_today(request, user) >= settings.runs_per_user_per_day and user.role != "admin":
        return fail("Daily limit of practice runs reached. Try again tomorrow.", 429)

    try:
        docs: list[tuple[str, str, ParsedFile]] = []
        vac = await read_upload(vacancy_file, max_bytes)
        if vac:
            docs.append(("vacancy", vac[1], parse_upload(vac[0], vac[1], max_bytes=max_bytes)))
        elif vacancy_text.strip():
            docs.append(("vacancy", "pasted.txt", parse_pasted(vacancy_text)))
        else:
            return fail("Add the vacancy as a file or pasted text.")
        cv = await read_upload(cv_file, max_bytes)
        if not cv:
            return fail("Add your CV (PDF or Word).")
        docs.append(("cv", cv[1], parse_upload(cv[0], cv[1], max_bytes=max_bytes)))
        extra = await read_upload(extra_file, max_bytes)
        if extra:
            docs.append(("notes", extra[1], parse_upload(extra[0], extra[1], max_bytes=max_bytes)))
        previous: Report | None = None
        prev = await read_upload(previous_file, max_bytes)
        if prev:
            previous = load_report(prev[0], prev[1])
    except (UploadError, ReportImportError) as e:
        return fail(str(e))

    try:
        run_id = create_run(
            app.state.engine,
            {
                "interview_type": interview_type,
                "language": language,
                "length": length,
                "answer_mode": answer_mode,
                "difficulty": difficulty,
            },
            user_id=user.id,
        )
    except ValueError as e:
        return fail(str(e))

    async def job() -> None:
        say = progress(request, run_id)
        key = settings.pii_encryption_key
        try:
            for kind, name, parsed in docs:
                say(f"reading {kind}")
                res = await add_document(
                    app.state.gateway, app.state.engine, run_id, kind, name, parsed, key
                )
                if res.kind_mismatch:
                    say(f"warning: the {kind} looks like a '{res.detected_kind}'")
                if res.injection_flag:
                    say(
                        f"warning: the {kind} contains text aimed at AI systems; it is treated as data only"
                    )
            await prepare(
                app.state.gateway, app.state.engine, run_id, key, previous=previous, progress=say
            )
            say("done")
        except LocalModelOffline:
            set_status(app.state.engine, run_id, "failed", "The local model went offline.")
        except Exception as e:
            log.exception("preparation failed")
            set_status(
                app.state.engine, run_id, "failed", f"Preparation failed ({type(e).__name__})."
            )

    spawn(request, run_id, job())
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_page(request: Request, run_id: str) -> Response:
    run = own_run(request, run_id)
    if run.status == "ready":
        return RedirectResponse(f"/runs/{run_id}/briefing", status_code=303)
    if run.status in ("interviewing", "paused"):
        return RedirectResponse(f"/runs/{run_id}/interview", status_code=303)
    if run.status == "done":
        return RedirectResponse(f"/runs/{run_id}/review", status_code=303)
    return render(
        request, "run_status.html", run=run, messages=request.app.state.progress.get(run_id, [])
    )


@router.get("/runs/{run_id}/events")
async def run_events(request: Request, run_id: str) -> StreamingResponse:
    """Server-sent events with preparation/review progress until the run changes state."""
    own_run(request, run_id)

    async def stream() -> Any:
        sent = 0
        for _ in range(900):  # at most ~15 minutes
            with Session(request.app.state.engine) as s:
                run = s.get(Run, run_id)
            messages = request.app.state.progress.get(run_id, [])
            for m in messages[sent:]:
                yield f"event: progress\ndata: {json.dumps(m)}\n\n"
            sent = len(messages)
            if run is None or run.status not in ("created", "preparing", "reviewing"):
                yield f"event: status\ndata: {json.dumps(run.status if run else 'gone')}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/briefing", response_class=HTMLResponse)
async def briefing_page(request: Request, run_id: str) -> HTMLResponse:
    run = own_run(request, run_id)
    mapping = load_mapping(
        request.app.state.engine, run_id, request.app.state.settings.pii_encryption_key
    )
    briefing = json.loads(mapping.restore(json.dumps(run.briefing)))
    with Session(request.app.state.engine) as s:
        reqs = {
            r.id: r for r in s.exec(select(Requirement).where(Requirement.run_id == run_id)).all()
        }
    return render(request, "briefing.html", run=run, b=briefing, reqs=reqs)


@router.get("/runs/{run_id}/interview", response_class=HTMLResponse)
async def interview_page(request: Request, run_id: str) -> Response:
    run = own_run(request, run_id)
    if run.status in ("reviewing", "done"):
        return RedirectResponse(f"/runs/{run_id}/review", status_code=303)
    ie = engine_for(request, run_id)
    try:
        question = await ie.start()
    except (LocalModelOffline, ProviderError) as e:
        return render(request, "error.html", 503, message=str(e))
    return render(
        request, "interview.html", run=run, question=question, progress=_interview_progress(ie)
    )


def _interview_progress(ie: InterviewEngine) -> dict[str, Any]:
    topics = ie.topics()
    state = ie._run().interview_state
    asked = [t for t in ie.turns() if t.role == "interviewer" and not t.practice_of]
    return {
        "question": len(asked),
        "follow_up": bool(asked) and asked[-1].next_move not in (None, "open"),
        "topic": int(state.get("topic_index", 0)) + 1,
        "topics": len(topics),
        "minutes": round(float(state.get("elapsed_s", 0)) / 60),
        "length": ie._run().settings.get("length", 30),
    }


@router.post("/runs/{run_id}/answer", response_class=HTMLResponse)
async def answer(
    request: Request,
    run_id: str,
    text: str = Form(...),
    audio_duration_s: float | None = Form(None),
) -> Response:
    run = own_run(request, run_id)
    ie = engine_for(request, run_id)
    try:
        result = await ie.answer(text, audio_duration_s=audio_duration_s)
    except LocalModelOffline:
        return render(request, "partials/offline.html", 503)
    except (ProviderError, BudgetExceeded) as e:
        return render(request, "partials/error.html", 503, message=str(e))
    htmx = request.headers.get("hx-request") == "true"
    if result.finished:
        await _start_review(request, run_id, ie)
        if not htmx:  # plain form post (no JavaScript): full page
            return RedirectResponse(f"/runs/{run_id}", status_code=303)
        return render(request, "partials/finished.html", run=run)
    if not htmx:
        return RedirectResponse(f"/runs/{run_id}/interview", status_code=303)
    return render(
        request,
        "partials/question.html",
        run=run,
        question=result.next_question,
        progress=_interview_progress(ie),
    )


async def _start_review(request: Request, run_id: str, ie: InterviewEngine) -> None:
    app = request.app

    async def job() -> None:
        await ie.drain()
        try:
            await finish(
                app.state.gateway,
                app.state.engine,
                run_id,
                app.state.settings.pii_encryption_key,
                progress=progress(request, run_id),
            )
        except Exception as e:
            log.exception("review failed")
            set_status(app.state.engine, run_id, "failed", f"Review failed ({type(e).__name__}).")
        app.state.interviews.pop(run_id, None)

    spawn(request, run_id, job())


@router.post("/runs/{run_id}/pause")
async def pause(request: Request, run_id: str) -> Response:
    own_run(request, run_id)
    engine_for(request, run_id).pause()
    return RedirectResponse("/", status_code=303)


@router.get("/runs/{run_id}/review", response_class=HTMLResponse)
async def review_page(request: Request, run_id: str) -> Response:
    run = own_run(request, run_id)
    if run.status != "done":
        return render(
            request, "run_status.html", run=run, messages=request.app.state.progress.get(run_id, [])
        )
    mapping = load_mapping(
        request.app.state.engine, run_id, request.app.state.settings.pii_encryption_key
    )
    report = build_report(request.app.state.engine, run_id, mapping=mapping, store=False)
    return render(
        request,
        "review.html",
        run=run,
        r=report,
        tips=all_tips(report.language),
        chart=json.dumps(_chart_data(report)),
    )


# ---------------------------------------------------------------- public demo (no login)

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
_demo_pdf: dict[str, bytes] = {}


class DemoRun:
    """Stands in for a Run on the review template; the demo has no database row."""

    id = "demo"
    status = "done"

    def __init__(self, settings: dict[str, Any], created_at: datetime) -> None:
        self.settings = settings
        self.created_at = created_at


def _demo(lang: str) -> dict[str, Any]:
    """A frozen real run with a fictional candidate (app/demo/<lang>.json, see demo/README.md)."""
    data: dict[str, Any] = json.loads((DEMO_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    data["report"] = Report.model_validate(data["report"])
    return data


def _demo_lang(request: Request) -> str:
    lang = lang_of(request)
    return lang if lang in ("nl", "en") else "nl"


@router.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request) -> HTMLResponse:
    d = _demo(_demo_lang(request))
    report: Report = d["report"]
    run = DemoRun(d["settings"], datetime.fromisoformat(report.created_at))
    return render(
        request,
        "review.html",
        demo=True,
        run=run,
        r=report,
        b=d["briefing"],
        reqs=d["requirements"],
        repo_url=request.app.state.settings.demo_repo_url,
        tips=all_tips(report.language),
        chart=json.dumps(_chart_data(report)),
    )


@router.get("/demo/report.pdf")
async def demo_pdf(request: Request) -> Response:
    lang = _demo_lang(request)
    if lang not in _demo_pdf:  # rendered once per language, then served from memory
        _demo_pdf[lang] = await asyncio.to_thread(to_pdf, _demo(lang)["report"])
    return Response(
        _demo_pdf[lang],
        media_type="application/pdf",
        headers={
            "Content-Disposition": download_header(
                _demo(lang)["report"].vacancy.title, "pdf", inline=True
            )
        },
    )


def _chart_data(r: Report) -> dict[str, Any]:
    return {
        "star": r.stats.get("star_rates", {}),
        "quality": r.stats.get("quality_distribution", {}),
        "speaking": [
            {"n": i + 1, "wpm": a.speaking.wpm, "fillers": a.speaking.fillers_per_min}
            for i, a in enumerate(r.answers)
            if a.speaking
        ],
    }


def download_header(title: str, ext: str, *, inline: bool = False) -> str:
    """Content-Disposition naming the file after the vacancy, e.g. "AI Engineer.pdf"."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")[:80] or "Interview Coach"
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip() or "Interview Coach"
    kind = "inline" if inline else "attachment"
    return (
        f'{kind}; filename="{ascii_name}.{ext}"; '
        f"filename*=UTF-8''{quote(name + '.' + ext, safe='')}"
    )


@router.get("/runs/{run_id}/report.json")
async def report_json(request: Request, run_id: str) -> Response:
    own_run(request, run_id)
    mapping = load_mapping(
        request.app.state.engine, run_id, request.app.state.settings.pii_encryption_key
    )
    report = build_report(request.app.state.engine, run_id, mapping=mapping, store=False)
    return Response(
        report.to_json(),
        media_type="application/json",
        headers={"Content-Disposition": download_header(report.vacancy.title, "json")},
    )


@router.get("/runs/{run_id}/report.pdf")
async def report_pdf(request: Request, run_id: str) -> Response:
    own_run(request, run_id)
    mapping = load_mapping(
        request.app.state.engine, run_id, request.app.state.settings.pii_encryption_key
    )
    report = build_report(request.app.state.engine, run_id, mapping=mapping, store=False)
    pdf = await asyncio.to_thread(to_pdf, report)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": download_header(report.vacancy.title, "pdf")},
    )


@router.post("/runs/{run_id}/delete")
async def delete_run(request: Request, run_id: str) -> Response:
    own_run(request, run_id)
    from app.retention import delete_run as purge

    purge(request.app.state.engine, run_id)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- speech


@router.post("/runs/{run_id}/transcribe")
async def transcribe(
    request: Request, run_id: str, audio: UploadFile = File(...), duration_s: float = Form(0.0)
) -> JSONResponse:
    from app.speech.transcribe import TranscriptionUnavailable, transcribe_bytes

    run = own_run(request, run_id)
    settings = request.app.state.settings
    data = await audio.read(25 * 1024 * 1024 + 1)
    try:
        transcriber = request.app.state.transcriber or _default_transcriber(settings.whisper_model)
        result = await asyncio.to_thread(
            transcribe_bytes,
            transcriber,
            data,
            str(run.settings.get("language", "nl")),
            duration_s,
            keep_dir=settings.data_dir / "audio" / run_id if settings.keep_audio else None,
        )
    except (ValueError, TranscriptionUnavailable) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(
        {
            "text": result.text,
            "duration_s": result.duration_s,
            "seconds_taken": result.seconds_taken,
        }
    )


def _default_transcriber(size: str) -> Any:
    from app.speech.transcribe import default_transcriber

    return default_transcriber(size)


# ---------------------------------------------------------------- practice


@router.get("/runs/{run_id}/practice/{turn_id}", response_class=HTMLResponse)
async def practice_page(request: Request, run_id: str, turn_id: str) -> HTMLResponse:
    run = own_run(request, run_id)
    mapping = load_mapping(
        request.app.state.engine, run_id, request.app.state.settings.pii_encryption_key
    )
    with Session(request.app.state.engine) as s:
        turns = sorted(s.exec(select(Turn).where(Turn.run_id == run_id)).all(), key=lambda t: t.seq)
    pair = next(((q, a) for q, a in qa_pairs(turns) if a.id == turn_id), None)
    if pair is None:
        raise HTTPException(status_code=404)
    attempts = [t for t in turns if t.practice_of == turn_id]
    return render(
        request,
        "practice.html",
        run=run,
        question=mapping.restore(pair[0].text_pseudonymised),
        original=mapping.restore(pair[1].text_pseudonymised),
        turn_id=turn_id,
        attempts=[_attempt_view(request, run, t, mapping) for t in [pair[1], *attempts]],
    )


def _attempt_view(request: Request, run: Run, turn: Turn, mapping: Any) -> dict[str, Any]:
    with Session(request.app.state.engine) as s:
        js = s.exec(select(Judgment).where(Judgment.turn_id == turn.id)).all()
    lang = str(run.settings.get("language", "nl"))
    sp = speaking_stats(turn.text_pseudonymised, turn.audio_duration_s, lang)
    return {
        "text": mapping.restore(turn.text_pseudonymised),
        "judgments": {judgment_key(j): j for j in js if j.question_id != "next_move"},
        "speaking": sp,
    }


@router.post("/runs/{run_id}/practice/{turn_id}")
async def practice_submit(
    request: Request,
    run_id: str,
    turn_id: str,
    text: str = Form(...),
    audio_duration_s: float | None = Form(None),
) -> Response:
    run = own_run(request, run_id)
    app = request.app
    key = app.state.settings.pii_encryption_key
    with Session(app.state.engine) as s:
        original = s.get(Turn, turn_id)
        topic = s.get(PlanTopic, original.topic_id) if original and original.topic_id else None
        reqs = [
            r
            for r in s.exec(select(Requirement).where(Requirement.run_id == run_id)).all()
            if topic and r.id in topic.requirement_ids
        ]
        turns = sorted(s.exec(select(Turn).where(Turn.run_id == run_id)).all(), key=lambda t: t.seq)
    if original is None or topic is None or original.run_id != run.id:
        raise HTTPException(status_code=404)
    question = next(q for q, a in qa_pairs(turns) if a.id == turn_id)
    mapping = load_mapping(app.state.engine, run_id, key)
    safe = await pseudonymise(app.state.gateway, text, mapping, run_id=run_id)
    from app.ingest.service import save_mapping

    save_mapping(app.state.engine, run_id, mapping, key)
    with Session(app.state.engine) as s:
        attempt = Turn(
            run_id=run_id,
            topic_id=topic.id,
            seq=len(turns) + 1,
            role="candidate",
            text_pseudonymised=safe.text,
            audio_duration_s=audio_duration_s,
            practice_of=turn_id,
        )
        s.add(attempt)
        s.commit()
        s.refresh(attempt)
    ie = InterviewEngine(app.state.gateway, app.state.engine, run_id, key)
    context = ie._evaluation_state(topic, question, safe)
    await evaluate_answer(
        app.state.gateway, app.state.engine, run_id, attempt.id, topic, context, reqs
    )
    return RedirectResponse(f"/runs/{run_id}/practice/{turn_id}", status_code=303)


# ---------------------------------------------------------------- tips and admin


@router.get("/tips", response_class=HTMLResponse)
async def tips_page(request: Request) -> HTMLResponse:
    require_user(request)
    return render(request, "tips.html", tips=all_tips(lang_of(request)))


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    require_admin(request)
    with Session(request.app.state.engine) as s:
        invites = s.exec(select(Invite)).all()
        users = s.exec(select(User)).all()
        runs = s.exec(select(Run)).all()
    per_run = [
        {
            "id": r.id[:8],
            "status": r.status,
            "created": r.created_at,
            **usage(request.app.state.engine, r.id),
        }
        for r in sorted(runs, key=lambda r: r.created_at, reverse=True)[:30]
    ]
    return render(
        request,
        "admin.html",
        u=usage(request.app.state.engine),
        invites=invites,
        users=users,
        runs=per_run,
        new_code=request.query_params.get("code"),
    )


@router.post("/admin/invites")
async def admin_invite(request: Request, role: str = Form("candidate")) -> Response:
    admin = require_admin(request)
    if role not in ("candidate", "coach", "admin"):
        raise HTTPException(status_code=400)
    code = create_invite(request.app.state.engine, admin.id, role)
    return RedirectResponse(f"/admin?code={code}", status_code=303)


@router.get("/admin/usage.json")
async def admin_usage(request: Request) -> JSONResponse:
    require_admin(request)
    return JSONResponse(usage(request.app.state.engine))
