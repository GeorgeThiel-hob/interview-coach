# Next steps that need the owner

The phase-by-phase plan for continuing in Cursor is in `docs/HANDOFF.md`.

Everything below is built and tested with fake providers; these steps need your machines,
accounts, data or judgment. Roughly in order.

## 1. First real run (closes M0 and M1)
- [x] Secrets only on the server: `deploy/init-env.sh`, then paste `ANTHROPIC_API_KEY`,
      `TYPESAFE_API_KEY`, `OLLAMA_BASE_URL` (docs/deploy.md step 3). No local `.env`.
- [ ] ~~`ollama pull`~~ (done) `make live` (real smoke tests).
- [ ] `make bench` and paste the table into the README ("model choice"); optionally add oMLX.
- [ ] `uv run coach run --vacancy <target vacancy> --cv <your CV> --length 15`: the M1
      acceptance run. Check `coach usage <run id>` and fill the README metrics table.
- [ ] Read the prompts in `prompts/` and the Jev criteria in `app/judgments/catalog.py` after
      that run; they are first drafts.

## 1b. Findings from the first real run (2026-09-27, 15-minute typed run)
- [ ] Time budget: typed answers took 1.3–6.5 min, not the assumed `minutes_per_exchange: 2`.
      Topic 1 used two follow-ups and the whole 15 minutes, so the engine jumped to the closing
      topic and **skipped topics 2 and 3**. Reserve time for every remaining planned topic before
      allowing a follow-up, based on elapsed time (`app/interview/engine.py` `_decide_move`).
- [ ] Interview header shows "Topic 1 / 4" while on question 3 (follow-ups stay in a topic).
      Show "Question N · topic x of y · follow-up".
- [ ] Preparation page (~3 min): indeterminate bar gives no sense of what is left. Show the
      step list up front with check marks and a filling bar.
- [ ] Confirm SSE is not buffered by nginx: progress lines must appear one by one.

## 2. Evaluation (M6, and the basis for trusting the badges)
- [ ] Write the eval set in `eval/set/` (format in eval/README.md): ~30 answers of known quality,
      ~10 bad/ungrounded interviewer questions, ~10 injection documents, plus clean ones.
- [ ] `make eval`; copy the suggested values into `config/thresholds.yaml`; commit the result.
- [ ] Add `TYPESAFE_API_KEY` as a GitHub Actions secret so CI runs the eval subset.

## 3. Deployment (M2)
- [x] Tailscale on laptop and server; Ollama bound to the laptop's Tailscale IP (docs/deploy.md).
- [x] Second DuckDNS subdomain, nginx site, certbot (`deploy/nginx-site.sh`).
- [x] `deploy/deploy.sh <user>@<server> <ssh-port>`, create the admin.
- [ ] Nightly backup cron + one tested restore (M6 criterion).
- [ ] Uptime monitor on `/healthz`.

## 4. Decisions still open
- [ ] D5 data policy check (TypeSafe, Anthropic, employer AI policy): docs/privacy.md.
- [ ] Speaking targets: words-per-minute band (120–160) and answer duration (60–120 s) in
      `app/review/metrics.py`.
- [ ] faster-whisper size (`WHISPER_MODEL` small/medium) and where it runs: on the server
      within the 0.5 CPU cap, or on the laptop. Measure a 1-minute answer (M5: under 20 s).
- [ ] Budget caps in `config/models.yaml` (EUR 1 per run, EUR 3 per day) and the USD→EUR rate.
- [ ] Make the repo public for the application (and add screenshots/metrics to the README).
- [ ] D7: compare `bge-m3` with a second embedding model (e.g. `qwen3-embedding`) in the eval.

## 5. Showcase for applications
- [ ] Public read-only `/demo` page: one complete run (briefing, interview, review with scores
      and charts) built from synthetic data, viewable without login. No model calls, no personal
      data, works while the laptop is offline. Build after the first real runs (phase 2), so
      the example reflects real output quality. Link it in the CV next to the GitHub repo.
- [ ] Screenshots or a short GIF of that demo in the README (phase 4).

## 6. Later (M7)
- [ ] Coach role with explicit report sharing; intake personas tuned with the account manager;
      fuller NL translation of the UI.
