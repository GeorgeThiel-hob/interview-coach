# Handoff: state of the project (v1.0, 2026-09-28)

Starting point for the next person or agent working on this repository. Read this, then
`CLAUDE.md` (build rules) and `AGENTS.md`.

## 1. Where things stand

- **v1.0 is complete** and runs in production on the reference deployment: prepare → briefing →
  interview → review → PDF → follow-up runs, web UI in Dutch and English (light and dark), a
  public read-only demo (`/demo`), and self-hosting documentation.
- Tested against the real providers (Ollama/Qwen 3.6 35B-A3B, Claude Sonnet 5, Jev 1.13.0) in
  several full runs; `make check` passes (~50 tests with fake providers) and `make live` passes.
- Measured costs, latencies and escalation rates are in [models.md](models.md) and the README.
- User documentation: [getting-started.md](getting-started.md) (one machine),
  [deploy.md](deploy.md) (server + model machine over Tailscale), [models.md](models.md).

## 2. Verified on the reference deployment

| Item | Result |
|---|---|
| Docker image (Pango/HarfBuzz on Debian slim, PDF export) | builds; PDFs with embedded fonts |
| Container → model machine through the host's Tailscale | works (`/healthz` `local_model: true`) |
| Server-sent events through nginx (`proxy_buffering off`) | progress steps stream live |
| Time budget and topic count | all planned topics covered in 15-minute runs |
| Guardrails | a fact-check question and a Chinese word from the local model were caught; regenerate and escalation paths fired in real runs |
| Spoken answers within 0.5 CPU / 768 MB | **not viable**: `small` runs out of memory, `base` takes 25 s for 55 s audio |

## 3. Rules that matter when working on a deployment

- **Secrets live only in the server's `.env`** (created by `deploy/init-env.sh`, chmod 600).
  Never print them; check a value with `grep -c '^NAME=.\+' .env`. Never commit `.env`.
- **The reference server is shared with other services.** Only touch the app's own directory,
  container, volume and nginx site; ask the owner before `sudo`, package installs or firewall
  changes; keep the container caps; reload nginx only after `nginx -t` passes.
- **Deploy when nobody is in a run** (background evaluations run in the app process); see
  deploy.md §10 for the check.
- **Public repo hygiene:** placeholders (`<server>`, `<your-domain>`, `100.x.y.z`) instead of
  real addresses; demo data and tests use fictional people only.
- Claude roles use Sonnet 5 (Haiku 4.5 for the cheap fallbacks); the owner does not want Opus for
  the app's own calls.

## 4. Open work

See [next-steps.md](next-steps.md). In short: backups need an off-server target; spoken answers
need a decision (more server memory or transcription on the model machine); the evaluation set
has to be written before the Jev thresholds can be tuned; the no-Claude configuration is
untested; `make bench` has not been run.

## 5. Known risks

| Item | Status |
|---|---|
| `launchctl setenv OLLAMA_HOST` does not survive a reboot of the model machine | re-run after reboot, or add a LaunchAgent |
| Local model language drift (Qwen switching to Chinese) | caught for interview questions in code; other local outputs (extraction) are not checked yet |
| Thresholds in `config/thresholds.yaml` | starting values from the spec, not tuned |
| Prompts, personas, tips | reviewed after the first real runs; tune further with the evaluation set |
