"""Freeze one finished run as public demo data (app/demo/<lang>.json). See demo/README.md.

Run inside the app container, with the id (or a unique prefix) of a run made with the
fictional documents in demo/source/:

    docker compose exec -T app /srv/.venv/bin/python scripts/export_demo_run.py <run-id> > nl.json

Only use runs with fictional documents: the output is published without login.
"""

from __future__ import annotations

import json
import sys

from sqlmodel import Session, select

from app.db.models import Requirement, Run
from app.db.session import make_engine
from app.ingest.service import load_mapping
from app.report.build import build_report
from app.settings import get_settings


def main(prefix: str) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    with Session(engine) as s:
        runs = [r for r in s.exec(select(Run)).all() if r.id.startswith(prefix)]
        if len(runs) != 1 or runs[0].status != "done":
            sys.exit(f"need exactly one finished run with id prefix {prefix!r}")
        run = runs[0]
        reqs = {
            r.id: {
                "text": r.text,
                "kind": r.kind,
                "evidence_strength": r.evidence_strength,
                "evidence_refs": r.evidence_refs,
            }
            for r in s.exec(select(Requirement).where(Requirement.run_id == run.id)).all()
        }
    mapping = load_mapping(engine, run.id, settings.pii_encryption_key)
    report = build_report(engine, run.id, mapping=mapping, store=False)
    out = {
        "settings": run.settings,
        "briefing": json.loads(mapping.restore(json.dumps(run.briefing))),
        "requirements": json.loads(mapping.restore(json.dumps(reqs))),
        "report": json.loads(report.to_json()),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
