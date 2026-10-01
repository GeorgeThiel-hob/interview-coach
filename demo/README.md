# Public demo (`/demo`)

A read-only page that shows one complete run without login: an intro that says plainly what the
page is (and is not), screenshots of the steps you cannot do on the page (new round, interview), the
briefing, the full review in a labelled "example result" frame, and a "try it yourself" block, in
Dutch and English. It makes no model calls, so it works while the laptop (local model) is off.

The "try it yourself" block has three states:

| State | When | Shows |
|---|---|---|
| open | `DEMO_SIGNUP_CODE` set, places left, before `DEMO_SIGNUP_UNTIL`, laptop online | a button to `/register?code=<code>` |
| offline | as above, but the local model does not answer within 2.5 s | "offline right now", plus `DEMO_CONTACT_EMAIL` |
| closed | no code, no places left, or past the end date | "access is by invitation", plus `DEMO_CONTACT_EMAIL` |

The shared code lets at most `DEMO_SIGNUP_MAX` (default 25) people register; their accounts have
`invited_by = "shared-signup"`. Personal invite codes (`coach invite`) keep working as before.
Cost per account stays bounded by `RUNS_PER_USER_PER_DAY` and the budget caps in `config/`.

The content is a **real run with fictional documents**: the candidate Sanne Visser and the
vacancy at "Gemeente Rivierstad" / "City of Riverton" do not exist. Everything shown is unedited
model output; only the answers were typed in character by a person.

| Path | What |
|---|---|
| `demo/source/` | the fictional vacancy and CV (NL and EN) and an answer sheet with the candidate's stories |
| `app/demo/nl.json`, `app/demo/en.json` | the frozen runs the page renders (settings, briefing, requirements, report) |
| `scripts/export_demo_run.py` | exports a finished run into that format |
| `app/templates/partials/demo_intro.html` | intro, walkthrough and briefing; the rest is `review.html` in demo mode |
| `app/templates/partials/demo_try.html` | the "try it yourself" block |
| `app/static/demo/<lang>-step1.png`, `-step2.png` | walkthrough screenshots, made by `scripts/demo_screens.py` |

## Refresh the demo

1. Log in and do a run with the documents from `demo/source/` (15 min, typed), answering in
   character with the answer sheet. One run per language.
2. Note the run id (the address `/runs/<id>/…`) and export it on the server:

   ```bash
   cd ~/interview-simulator/deploy
   docker compose exec -T app /srv/.venv/bin/python scripts/export_demo_run.py <id> > /tmp/nl.json
   ```
3. Copy the file into `app/demo/` in the repo, check it contains only fictional data.
4. Remake the screenshots (they show the new round form and a follow-up question from this run;
   needs Google Chrome): `uv run python scripts/demo_screens.py`. Do this after template changes too.
5. Commit and deploy.

Optional settings in `.env`: `DEMO_REPO_URL` (link to the source code), and for the "try it
yourself" block `DEMO_SIGNUP_CODE`, `DEMO_SIGNUP_MAX`, `DEMO_SIGNUP_UNTIL` (YYYY-MM-DD) and
`DEMO_CONTACT_EMAIL`.
