# Decisions log

Open decisions come from spec section 14. Newest first.

## 2026-10-01 (public demo)

- **D3 amended: one shared sign-up code on `/demo`, next to the personal invites.** So people
  who find the demo page can try the app without first asking for an invite. Capped
  (`DEMO_SIGNUP_MAX`, default 25 accounts), optionally dated (`DEMO_SIGNUP_UNTIL`), off unless
  `DEMO_SIGNUP_CODE` is set; the button shows only while the local model answers. The code is
  public by design: the cap, end date, per-user run limit and budget caps are the protection.
  Rejected: fully open guest runs without an account (no cap on strangers' uploads or cost),
  and request-by-mail only (an interviewer would have to wait for a reply). The cap lives in
  settings, not in an `invites.max_uses` column, because the database is created with
  `create_all` only and has no migrations.
- **Claude roles → `claude-sonnet-5-5`** (from `claude-sonnet-5`), same price per token.

## 2026-09-27 (build)

- **D3 auth → invite codes + password (argon2).** Default from the spec; no e-mail sending needed.
- **D4 UI language → NL-first with an EN switch.** Spec default. Only the main labels are
  translated so far; interview content follows the run's language setting.
- **D6 frontend → Jinja2 + HTMX + Alpine + Chart.js.** Spec default; no build step.
- **D8 retention → 30 days**, configurable (`RETENTION_DAYS`).
- **Deploy → `deploy/deploy.sh` from the laptop (rsync + docker compose).** Rejected: a GitHub
  Action with SSH access, because the server also runs other services.
- **Interviewer questions are shown after the guardrail check, not streamed token by token.**
  Streaming would show questions before Jev has checked them. SSE is used for progress instead.
- **Follow-ups yield to coverage:** a follow-up is only asked while every remaining planned topic
  still fits in the time budget (found in testing: early follow-ups crowded out re-tested weak
  points in 15-minute runs).
- **Next-move and guardrails do not escalate to Claude** (latency between turns). An uncertain
  next move falls back to a code rule; an uncertain guardrail counts as a failure.
- **Speech-to-text on the server CPU with faster-whisper (optional dependency group).** Whether
  this meets "1 minute in under 20 s" within the container's 0.5 CPU cap is untested; if not,
  either raise the cap during transcription or transcribe on the laptop.

## 2026-09-27

- **D1: where the local model runs → the owner's laptop (Apple Silicon, 32 GB) over Tailscale.**
  Qwen and the embedding model run in Ollama on the laptop; the server reaches it over a private
  Tailscale network, and Ollama is never exposed publicly. Default model: `qwen3.6:35b-a3b`
  (q4_K_M, 23 GB, mixture-of-experts with ~3B active parameters). Alternative:
  `qwen3.8:27b` (q4_K_M, 18 GB, dense: newer, likely slower per token). Tags taken from
  ollama.com/library on this date. M1 benchmarks both on speed and picks one on the numbers.
  Rejected: CPU on the server (shared with other services, 2 vCPU / 8 GB), a GPU server (cost).
- **Laptop offline → block new runs.** Pseudonymisation needs the local model, and falling back to
  Claude would send unredacted CVs out. Finished runs, reviews and reports keep working.
  Rejected: regex-only pseudonymisation plus a Claude fallback.
- **D2: Jev access → TypeSafe directly, via the Python `typesafe-sdk`.** Rejected: OpenRouter.
- **D7: embedding model → `bge-m3` as default** (multilingual, handles Dutch); compare with a
  second model in the eval.
- **Hosting → an existing small VPS shared with other services.** Low use (a few interview preps a year). The app
  runs in Docker with CPU/memory caps. The server's nginx already owns ports 80/443, so there is
  no Caddy container (spec 11.1 deviation); nginx will proxy a second DuckDNS subdomain to the
  app on `127.0.0.1:8090` (M2). Rejected: a separate small server.
- **Local runtime → Ollama as default, oMLX as a benchmarked alternative.** Ollama is widely known,
  runs on Linux as well as macOS, and covers chat, JSON-schema output and embeddings in one
  service. oMLX (github.com/jundot/omlx, Apache 2.0, MLX-based, OpenAI-compatible, API key
  required on network binds) is added as a second local provider in M1 and compared on the same
  prompts, so the runtime choice is made on measured numbers. Rejected: oMLX as the default
  (macOS-only, younger single-maintainer project).
- **Pinned versions:** Jev `jev-1.13.0`; `typesafe-sdk==0.7.2` (the docs snapshot describes
  0.7.1; 0.7.2 was the current release on PyPI on this date).
- **D5 (owner's own use) → accepted, 2026-09-27.** Pseudonymised text from the owner's own
  documents and answers may go to Anthropic and TypeSafe; the remaining content is already public
  in the owner's applications and profiles. Colleague use still needs the D5 checklist in
  `docs/privacy.md`. Rejected: fully local processing (noticeably weaker feedback).
- **Retries live in the gateway.** The SDKs' own retries are switched off so every provider
  retries, times out and logs the same way (spec 6.3).
