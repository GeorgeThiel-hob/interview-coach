"""Command line (M1): ``coach run --vacancy x.pdf --cv y.pdf``.

coach run --vacancy vacature.pdf --cv cv.pdf [--previous report.pdf] [--lang nl]
          [--length 15] [--type mixed] [--difficulty realistic] [--out reports/]
coach resume RUN_ID
coach usage [RUN_ID]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import Engine

from app.db.session import make_engine
from app.ingest.parse import UploadError, parse_upload
from app.interview.engine import InterviewEngine
from app.llm.errors import BudgetExceeded, LocalModelOffline, ProviderError
from app.llm.gateway import Gateway, build_gateway
from app.pipeline import add_document, create_run, finish, prepare
from app.report.export import ReportImportError, load_report, to_pdf
from app.report.schema import Report
from app.review.usage import usage
from app.settings import get_settings


def pii_key() -> str:
    settings = get_settings()
    if settings.pii_encryption_key:
        return settings.pii_encryption_key
    path = settings.data_dir / ".pii_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(Fernet.generate_key().decode())
        path.chmod(0o600)
        print(f"(created a local PII encryption key in {path}; set PII_ENCRYPTION_KEY on a server)")
    return path.read_text().strip()


def setup() -> tuple[Gateway, Engine]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    return build_gateway(engine), engine


def read_answer() -> str:
    print("\nYour answer (finish with an empty line; /pause to stop and resume later):")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        if line.strip() in ("/pause", "/quit"):
            return line.strip()
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


async def interview(gw: Gateway, engine: Engine, run_id: str, key: str) -> bool:
    ie = InterviewEngine(gw, engine, run_id, key)
    question = await ie.start()
    while True:
        persona = (question.persona or "interviewer").replace("_", " ")
        print(f"\n[{persona}] {question.text_pseudonymised}")
        text = read_answer()
        if text in ("/pause", "/quit") or not text:
            ie.pause()
            await ie.drain()
            print(f"\nPaused. Resume with: coach resume {run_id}")
            return False
        result = await ie.answer(text)
        if result.finished or result.next_question is None:
            await ie.drain()
            return True
        question = result.next_question


async def review_and_save(gw: Gateway, engine: Engine, run_id: str, key: str, out: Path) -> Report:
    report = await finish(gw, engine, run_id, key, progress=lambda m: print(f"  … {m}"))
    out.mkdir(parents=True, exist_ok=True)
    (out / f"report-{run_id[:8]}.json").write_text(report.to_json(), encoding="utf-8")
    try:
        (out / f"report-{run_id[:8]}.pdf").write_bytes(to_pdf(report))
    except OSError as e:  # WeasyPrint needs pango on the system
        print(f"(PDF skipped: {e})")
    print(f"\nReport saved in {out}/ (report-{run_id[:8]}.json and .pdf)")
    stats = report.stats
    print("STAR:", ", ".join(f"{k} {v:.0%}" for k, v in stats.get("star_rates", {}).items()))
    for p in report.practice_plan:
        print(f" - {p.action}")
    return report


async def cmd_run(args: argparse.Namespace) -> int:
    gw, engine = setup()
    key = pii_key()
    if not await gw.local_available():
        print(
            "The local model (Ollama) is not reachable. New runs are blocked so that raw "
            "documents never leave your machines. Start Ollama and try again."
        )
        return 2
    previous: Report | None = None
    if args.previous:
        try:
            previous = load_report(Path(args.previous).read_bytes(), args.previous)
        except ReportImportError as e:
            print(f"Previous report: {e}")
            return 2
    settings = {
        "language": args.lang,
        "length": args.length,
        "interview_type": args.type,
        "difficulty": args.difficulty,
        "answer_mode": "typed",
    }
    run_id = create_run(engine, settings)
    print(f"Run {run_id}")
    try:
        for kind, path in (("vacancy", args.vacancy), ("cv", args.cv)):
            parsed = parse_upload(Path(path).read_bytes(), Path(path).name)
            print(f"  … reading and pseudonymising the {kind}")
            res = await add_document(gw, engine, run_id, kind, Path(path).name, parsed, key)
            if res.kind_mismatch:
                print(f"  ! {path} looks like a '{res.detected_kind}', not a {kind}. Continuing.")
            if res.injection_flag:
                print(f"  ! {path} contains text aimed at AI systems; it is treated as data only.")
        await prepare(
            gw, engine, run_id, key, previous=previous, progress=lambda m: print(f"  … {m}")
        )
        print_briefing(engine, run_id)
        input("\nPress Enter to start the interview...")
        if await interview(gw, engine, run_id, key):
            await review_and_save(gw, engine, run_id, key, Path(args.out))
        print_usage(engine, run_id)
    except UploadError as e:
        print(f"Upload problem: {e}")
        return 2
    except LocalModelOffline:
        print(
            "The local model went offline. The run is saved; resume with "
            f"`coach resume {run_id}` once Ollama is back."
        )
        return 2
    except (ProviderError, BudgetExceeded) as e:
        print(f"Stopped: {e}")
        return 1
    finally:
        await gw.aclose()
    return 0


async def cmd_resume(args: argparse.Namespace) -> int:
    gw, engine = setup()
    key = pii_key()
    try:
        if await interview(gw, engine, args.run_id, key):
            await review_and_save(gw, engine, args.run_id, key, Path(args.out))
        print_usage(engine, args.run_id)
    finally:
        await gw.aclose()
    return 0


def print_briefing(engine: Engine, run_id: str) -> None:
    from sqlmodel import Session

    from app.db.models import Run

    with Session(engine) as s:
        run = s.get(Run, run_id)
    b = run.briefing if run else {}
    print("\n=== Briefing ===")
    for q in b.get("likely_questions", []):
        print(f" ? {q}")
    for e in b.get("strongest_evidence", []):
        print(f" + {e['requirement_id']}: {e['summary']} [{', '.join(e.get('chunk_refs', []))}]")
    for g in b.get("gaps", []):
        print(f" - {g['requirement_id']}: {g['advice']}")
    for p in b.get("prepare", []):
        print(f" * prepare: {p}")


def print_usage(engine: Engine, run_id: str | None) -> None:
    u = usage(engine, run_id)
    print(
        f"\nModel calls: {u['calls']} · local share {u['local_share']:.0%} · cost EUR {u['cost_eur']:.4f}"
    )
    esc = sum(v["escalated"] for v in u["escalation"].values())
    tot = sum(v["total"] for v in u["escalation"].values())
    print(f"Judgments: {tot} · escalated to Claude: {esc}")


def admin_command(args: argparse.Namespace) -> int:
    import getpass

    from sqlmodel import Session, select

    from app.db.models import User
    from app.retention import purge_old_runs
    from app.web.auth import create_invite, create_user

    _, engine = setup()
    if args.cmd == "create-admin":
        password = getpass.getpass("Password (min. 10 characters): ")
        if len(password) < 10:
            print("Password too short.")
            return 2
        user = create_user(engine, args.email, password, role="admin")
        print(f"Admin {user.email} created.")
    elif args.cmd == "invite":
        with Session(engine) as s:
            admin = s.exec(select(User).where(User.role == "admin")).first()
        if admin is None:
            print("Create an admin first: coach create-admin --email ...")
            return 2
        code = create_invite(engine, admin.id, args.role)
        print(f"Invite code: {code}  (register at /register?code={code})")
    else:
        removed = purge_old_runs(engine, get_settings().retention_days)
        print(f"Removed {removed} runs older than {get_settings().retention_days} days.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coach", description="Interview Coach")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="prepare and run an interview")
    run.add_argument("--vacancy", required=True)
    run.add_argument("--cv", required=True)
    run.add_argument("--previous", help="report.json or report.pdf from an earlier run")
    run.add_argument("--lang", default="nl", choices=["nl", "en"])
    run.add_argument("--length", type=int, default=15, choices=[15, 30, 45])
    run.add_argument("--type", default="mixed", choices=["intake", "client", "mixed"])
    run.add_argument(
        "--difficulty", default="realistic", choices=["friendly", "realistic", "critical"]
    )
    run.add_argument("--out", default="reports")
    resume = sub.add_parser("resume", help="continue a paused interview")
    resume.add_argument("run_id")
    resume.add_argument("--out", default="reports")
    use = sub.add_parser("usage", help="model call metrics")
    use.add_argument("run_id", nargs="?")
    admin = sub.add_parser("create-admin", help="create the first admin account")
    admin.add_argument("--email", required=True)
    inv = sub.add_parser("invite", help="create an invite code")
    inv.add_argument("--role", default="candidate", choices=["candidate", "coach", "admin"])
    sub.add_parser("purge", help="delete runs older than the retention period")
    args = parser.parse_args(argv)
    if args.cmd in ("create-admin", "invite", "purge"):
        return admin_command(args)
    if args.cmd == "usage":
        _, engine = setup()
        print(json.dumps(usage(engine, args.run_id), indent=2))
        return 0
    handler = cmd_run if args.cmd == "run" else cmd_resume
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
