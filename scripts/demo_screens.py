"""Screenshots for the /demo walkthrough: app/static/demo/<lang>-step1.png and -step2.png.

Renders the real templates (new round form; interview screen) with the frozen demo run in
app/demo/<lang>.json, then photographs them with headless Chrome. No server, no model calls.
Run again after a template or demo-run change:

    uv run python scripts/demo_screens.py [--chrome PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.web.i18n import translate  # noqa: E402
from app.web.routes import TEMPLATES  # noqa: E402

OUT = ROOT / "app" / "static" / "demo"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTH, HEIGHT, OUT_WIDTH = 1200, 800, 1600  # CSS viewport; saved PNG width (2x render, scaled)


def context(lang: str, **ctx: Any) -> dict[str, Any]:
    user = SimpleNamespace(role="candidate", email="sanne@example.org")
    return {"t": lambda k: translate(k, lang), "lang": lang, "user": user, "csrf": "x", **ctx}


def follow_up(run: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """The first question asked because the interviewer decided to probe deeper."""
    answers = run["report"]["answers"]
    for i in range(1, len(answers)):
        if answers[i - 1]["judgments"].get("next_move", {}).get("value") == "probe_deeper":
            return i, answers[i]
    raise SystemExit("demo run has no follow-up question")


def step1(lang: str) -> str:
    return TEMPLATES.env.get_template("new_run.html").render(
        context(lang, local_ok=True, speech_ok=False)
    )


def step2(lang: str, run: dict[str, Any]) -> str:
    i, a = follow_up(run)
    answers = run["report"]["answers"]
    topics = list(dict.fromkeys(x["topic"] for x in answers))
    length = int(run["settings"].get("length", 30))
    progress = {
        "question": i + 1,
        "follow_up": True,
        "topic": topics.index(a["topic"]) + 1,
        "topics": len(topics),
        # the frozen run keeps no clock; spread the length evenly over the questions
        "minutes": round(length * i / len(answers)),
        "length": length,
    }
    html = TEMPLATES.env.get_template("interview.html").render(
        context(
            lang,
            run=SimpleNamespace(id="demo", settings=run["settings"]),
            question=SimpleNamespace(persona=a["persona"], text_pseudonymised=a["question"]),
            progress=progress,
            speech_ok=False,
        )
    )
    # the candidate halfway through typing their real answer from this run
    typed = ""
    for sentence in re.split(r"(?<=[.!?])\s+", a["answer"].strip()):
        typed = f"{typed} {sentence}".strip()
        if len(typed) >= 120:
            break
    return html.replace("required></textarea>", f"required>{escape(typed)}</textarea>")


def shoot(chrome: str, html: str, tmp: Path, name: str) -> None:
    html = html.replace('"/static/', f'"{(ROOT / "app" / "static").as_uri()}/')
    html = html.replace("<html ", '<html data-theme="light" ', 1)
    page = tmp / f"{name}.html"
    page.write_text(html, encoding="utf-8")
    raw = tmp / f"{name}.png"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={WIDTH},{HEIGHT}",
            f"--screenshot={raw}",
            page.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    out = OUT / f"{name}.png"
    shutil.copy(raw, out)
    if shutil.which("sips"):  # macOS: scale the 2x render down to keep the file small
        subprocess.run(["sips", "-Z", str(OUT_WIDTH), str(out)], check=True, capture_output=True)
    print(out.relative_to(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chrome", default=CHROME)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        for lang in ("nl", "en"):
            run = json.loads((ROOT / "app" / "demo" / f"{lang}.json").read_text(encoding="utf-8"))
            shoot(args.chrome, step1(lang), Path(d), f"{lang}-step1")
            shoot(args.chrome, step2(lang, run), Path(d), f"{lang}-step2")


if __name__ == "__main__":
    main()
