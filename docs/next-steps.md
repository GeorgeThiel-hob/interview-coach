# Next steps

State after v1.1 (2026-10-01). Overview: [README](../README.md); build rules: [CLAUDE.md](../CLAUDE.md).

## Done for v1.1
- [x] `/demo` says what it is: two ways in at the top (try it yourself / look around first),
      screenshots of the new-round form and a real follow-up question (`scripts/demo_screens.py`),
      the review in a labelled "example result" frame.
- [x] "Try it yourself": one shared sign-up code (`DEMO_SIGNUP_CODE`, capped by
      `DEMO_SIGNUP_MAX`, dated by `DEMO_SIGNUP_UNTIL`); the button shows only while the local
      model answers. Decision D3 amended (docs/decisions.md).
- [x] Accounts use a username (3–40 characters), no e-mail address needed; existing e-mail
      logins keep working.
- [x] Claude roles on `claude-sonnet-5-5`; verified on a real run (all calls served by
      Sonnet 5.5, €0.21 for 15 minutes).
- [x] Non-ASCII codes on `/register` give a 400 instead of a 500.

## Done for v1.0
- [x] Real providers: `make live` passes (Ollama, Claude, Jev); full runs in Dutch and English.
- [x] Deployment: Docker, Tailscale (tagged server, ACL), nginx + certbot (`deploy/nginx-site.sh`),
      https, admin account; SSE progress verified through nginx.
- [x] Fixes from the first real runs: time budget per topic, topic count per length, no
      fact-check questions, CJK characters rejected, one language per page and report, readable
      PDF labels, step-by-step progress, Dutch tips, empty-briefing fallback.
- [x] Design v0.2 (Terracotta) for the web UI and the PDF; files named after the vacancy.
- [x] Public `/demo` page (NL + EN) from real runs with a fictional candidate; README screenshots
      and measured costs/latencies.
- [x] D5 for the owner's own use (docs/decisions.md).
- [x] Self-hosting documentation: getting-started, deploy, models.

## Needs the owner
- [ ] **Backups**: choose an off-server SSH/SFTP target (e.g. a storage box), then set up
      `deploy/backup.sh` + the cron line and test one restore (docs/deploy.md §9).
- [ ] **Spoken answers**: decide between raising the container memory to 1.5 GB+ during
      transcription, or transcribing on the model machine. Measured within 0.5 CPU / 768 MB:
      `small` runs out of memory, `base` takes 25 s for a 55 s answer and misreads technical terms.
- [ ] **Evaluation set** in `eval/set/` (format in eval/README.md): ~30 answers of known quality,
      ~10 bad interviewer questions, ~10 injection documents; then `make eval` and copy the
      suggested thresholds into `config/thresholds.yaml`. Add `TYPESAFE_API_KEY` as a GitHub
      Actions secret so CI runs the eval subset.
- [ ] Uptime monitor on `https://<your-domain>/healthz`.
- [ ] Budget caps (`config/models.yaml`: €1 per run, €3 per day) and the USD→EUR rate.
- [ ] D5 before other people use the instance (TypeSafe and Anthropic data terms, employer AI
      policy): docs/privacy.md.

## Engineering
- [ ] **Haiku**: `claude-haiku-4-5` (roles `interviewer_escalation`, `fallback_fast` in
      `config/models.yaml`) may be retired from 2026-10-15; switch both roles to the next Haiku
      when it is released, and add its price under `pricing_usd_per_mtok`.
- [ ] "Try it yourself" ignores the daily budget: when `budgets.daily_eur` is used up, show
      "busy today" instead of the button.
- [ ] Test the no-Claude configuration end to end (every generating role on Ollama) with the
      evaluation set; document the quality difference.
- [ ] `make bench`: Qwen 3.6 35B-A3B vs 3.8 27B (and MLX / oMLX) on the reference machine; add the
      table to docs/models.md.
- [ ] Check other local-model outputs (requirement extraction) for language drift, like the
      interviewer questions.
- [ ] Coverage "in documents: none" for an experience requirement that the CV does show; check
      the evidence map (`evidence_for_req`, thresholds `evidence.strong/partial`).
- [ ] Speaking targets (120–160 words per minute, 60–120 s per answer) in `app/review/metrics.py`.
- [ ] D7: compare `bge-m3` with a second embedding model in the evaluation.

## Known risks
- `launchctl setenv OLLAMA_HOST` does not survive a reboot of the model machine: run it again, or
  add a LaunchAgent.
- Language drift of the local model is caught for interview questions only, not yet for other
  local outputs (requirement extraction).
- Thresholds in `config/thresholds.yaml` are starting values from the spec, not tuned.
- Deploy only when no run is in progress (background evaluations run in the app process).

## Later (M7)
- [ ] Coach role with explicit report sharing; intake personas tuned with an account manager.
