# Public demo (`/demo`)

A read-only page that shows one complete run without login: an intro, the briefing, and the full
review (charts, requirement coverage, feedback per answer), in Dutch and English. It makes no
model calls and does not touch the database, so it works while the laptop (local model) is off.

The content is a **real run with fictional documents**: the candidate Sanne Visser and the
vacancy at "Gemeente Rivierstad" / "City of Riverton" do not exist. Everything shown is unedited
model output; only the answers were typed in character by a person.

| Path | What |
|---|---|
| `demo/source/` | the fictional vacancy and CV (NL and EN) and an answer sheet with the candidate's stories |
| `app/demo/nl.json`, `app/demo/en.json` | the frozen runs the page renders (settings, briefing, requirements, report) |
| `scripts/export_demo_run.py` | exports a finished run into that format |
| `app/templates/partials/demo_intro.html` | intro and briefing; the rest is `review.html` in demo mode |

## Refresh the demo

1. Log in and do a run with the documents from `demo/source/` (15 min, typed), answering in
   character with the answer sheet. One run per language.
2. Note the run id (the address `/runs/<id>/…`) and export it on the server:

   ```bash
   cd ~/interview-simulator/deploy
   docker compose exec -T app /srv/.venv/bin/python scripts/export_demo_run.py <id> > /tmp/nl.json
   ```
3. Copy the file into `app/demo/` in the repo, check it contains only fictional data, commit and
   deploy.

Optional: set `DEMO_REPO_URL` in `.env` to show a link to the source code on the page.
