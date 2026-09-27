# Next steps that need the owner

The phase-by-phase plan for continuing in Cursor is in `docs/HANDOFF.md`.

Everything below is built and tested with fake providers; these steps need your machines,
accounts, data or judgment. Roughly in order.

## 1. First real run (closes M0 and M1)
- [ ] Secrets only on the server: `deploy/init-env.sh`, then paste `ANTHROPIC_API_KEY`,
      `TYPESAFE_API_KEY`, `OLLAMA_BASE_URL` (docs/deploy.md step 3). No local `.env`.
- [ ] `ollama pull qwen3.6:35b-a3b && ollama pull bge-m3`, then `make live` (real smoke tests).
- [ ] `make bench` and paste the table into the README ("model choice"); optionally add oMLX.
- [ ] `uv run coach run --vacancy <Defensie vacancy> --cv <your CV> --length 15`: the M1
      acceptance run. Check `coach usage <run id>` and fill the README metrics table.
- [ ] Read the prompts in `prompts/` and the Jev criteria in `app/judgments/catalog.py` after
      that run; they are first drafts.

## 2. Evaluation (M6, and the basis for trusting the badges)
- [ ] Write the eval set in `eval/set/` (format in eval/README.md): ~30 answers of known quality,
      ~10 bad/ungrounded interviewer questions, ~10 injection documents, plus clean ones.
- [ ] `make eval`; copy the suggested values into `config/thresholds.yaml`; commit the result.
- [ ] Add `TYPESAFE_API_KEY` as a GitHub Actions secret so CI runs the eval subset.

## 3. Deployment (M2)
- [ ] Tailscale on laptop and server; Ollama bound to the laptop's Tailscale IP (docs/deploy.md).
- [ ] Second DuckDNS subdomain, nginx site, certbot.
- [ ] `deploy/deploy.sh botuser@<server> 2222`, create the admin, invite yourself.
- [ ] Nightly backup cron + one tested restore (M6 criterion).
- [ ] Uptime monitor on `/healthz`.

## 4. Decisions still open
- [ ] D5 data policy check (TypeSafe, Anthropic, House of Bèta AI policy): docs/privacy.md.
- [ ] Speaking targets: words-per-minute band (120–160) and answer duration (60–120 s) in
      `app/review/metrics.py`.
- [ ] faster-whisper size (`WHISPER_MODEL` small/medium) and where it runs: on the server
      within the 0.5 CPU cap, or on the laptop. Measure a 1-minute answer (M5: under 20 s).
- [ ] Budget caps in `config/models.yaml` (EUR 1 per run, EUR 3 per day) and the USD→EUR rate.
- [ ] Make the repo public for the application (and add screenshots/metrics to the README).
- [ ] D7: compare `bge-m3` with a second embedding model (e.g. `qwen3-embedding`) in the eval.

## 5. Later (M7)
- [ ] Coach role with explicit report sharing; intake personas tuned with the account manager;
      fuller NL translation of the UI.
