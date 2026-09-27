# Handoff: continue in Cursor (local checkout + server over SSH)

Written 2026-09-27 at the end of the first build session (Claude Code, cloud). This file is the
starting point for the next agent. Read it fully, then `CLAUDE.md`.

## 1. Where things stand

- All milestones M0–M6 of `docs/scope.md` are **implemented and tested with fake providers**
  (`make check`: lint, format, mypy strict on `app/llm` + `app/judgments`, 35 tests).
- **Nothing has run against the real providers yet**: Ollama/Qwen, Claude, Jev, faster-whisper.
- **The Docker image has never been built**: the cloud session could not pull base images.
  Building it on the server is the first real check (`Dockerfile` installs Pango/fonts for PDFs).
- The web app was clicked through in a headless browser with fake models: pages render on
  desktop and mobile, no console or server errors.
- Code map: see "Where things are" in `CLAUDE.md`. Owner task list: `docs/next-steps.md`.

## 2. The owner's wishes (keep these)

1. **Same local directory:** `~/Documents/portfolio-projects/interview-simulator`, kept in sync
   with `main` on GitHub. Work on feature branches; the owner merges.
2. **Cursor agent with SSH access to the server** sets up the infrastructure and migrates the
   needed files. Deploys go through `deploy/deploy.sh` (rsync + docker compose), not a CI job
   with SSH keys.
3. **Infrastructure first**, then testing through the web UI (HTML) on the server.
4. **Secrets live only on the server.** `deploy/init-env.sh` creates `.env` there with
   `chmod 600` and generates the internal secrets; the owner pastes the API keys himself.
   **No `.env` in the local directory**, ever. The repo keeps `.env.example`: every variable,
   empty, with an explanation, so it shows on GitHub what has to be filled in.
5. **The repo becomes public** and must be documented well enough that someone else can
   reproduce the exact setup with open-source tools (`README.md`, `docs/deploy.md`,
   `docs/architecture.md`, `docs/privacy.md`). No personal data, hostnames, IPs or e-mail
   addresses in the repo: use placeholders.

## 3. Rules for the agent (in addition to CLAUDE.md)

**Secrets**
- Never write a secret to a local file, a commit, a log, a chat message or a command line
  that echoes it. Never `cat .env`; to check a value is set, use
  `grep -c '^ANTHROPIC_API_KEY=.\+' .env`.
- Running `deploy/init-env.sh` on the server is fine: it prints no secrets. The owner pastes
  the API keys into the file himself.
- Before any push to a public repo: scan for secrets
  (`git grep -nE 'sk-ant-|BEGIN .*PRIVATE KEY|api_key\s*=\s*["\x27][A-Za-z0-9]{12,}'`).

**The server is shared with the owner's trading bot. It must never be disturbed.**
- Allowed footprint: `~/interview-simulator/` (the app), `deploy/docker-compose.yml`'s
  container and volume, `/etc/nginx/sites-available/interview` (+ its symlink), a certbot
  certificate for the app's own domain, one cron line for `deploy/backup.sh`.
- Never touch the bot's directories, services, systemd units, cron entries, databases or its
  nginx site. Never restart nginx without `sudo nginx -t` passing first; use `reload`.
- Read-only inspection (`docker ps`, `df -h`, `free -m`, `nginx -T | head`, `tailscale status`)
  is fine. Ask the owner before any `sudo`, package install, firewall change or anything
  outside the allowed footprint, and show the exact command first.
- The container is capped at 0.5 CPU and 768 MB on purpose. Do not raise the caps without
  asking (speech transcription may be a reason: see section 6).

**Public repo hygiene:** placeholders (`<server>`, `<your-domain>`, `100.x.y.z`) instead of
real values in docs and scripts. Server-specific values live in the owner's head or in the
server's `.env`.

## 4. Phases

### Phase 0: sync the local directory (owner, in the Cursor terminal)
```bash
cd ~/Documents/portfolio-projects/interview-simulator
git fetch origin
git checkout main
git pull --ff-only origin main    # if refused: git reset --hard origin/main (discards local changes)
git branch -a                     # old claude/* branches can be deleted after the merge
ls -a | grep -x .env && echo "REMOVE the local .env" || echo "no local .env: good"
uv sync                           # local tooling for make check (needs uv: brew install uv)
make check
```

### Phase 1: infrastructure (agent with SSH, owner approves privileged steps)
1. Read-only survey of the server: OS, free disk and memory, Docker + compose plugin, nginx
   version and existing sites, certbot, Tailscale, open ports. Report before changing anything.
2. Laptop: Tailscale on and in the same tailnet; `ollama pull qwen3.6:35b-a3b` and
   `ollama pull bge-m3`; bind Ollama to the Tailscale IP (`docs/deploy.md` step 2); from the
   server: `curl http://100.x.y.z:11434/api/tags`.
3. `deploy/deploy.sh <user>@<server> <ssh-port>` from the laptop (runs `make check`, rsyncs).
4. On the server: `deploy/init-env.sh`; the **owner** pastes `ANTHROPIC_API_KEY`,
   `TYPESAFE_API_KEY`, `OLLAMA_BASE_URL`; `chmod 600 .env` is already set by the script.
5. `cd deploy && docker compose build --build-arg WITH_DEV=1 && docker compose up -d`.
   First build: fix whatever the Dockerfile needs (never verified, see section 1).
6. `curl -s http://127.0.0.1:8090/healthz` must show `local_model: true`. If not: container →
   Tailscale routing (command in `docs/deploy.md` step 3).
7. DuckDNS subdomain → nginx site from `deploy/nginx-interview.conf` → certbot → reload.
8. `coach create-admin`, `coach invite`; log in over HTTPS.

### Phase 2: real tests (through the web UI)
1. `docker compose exec app uv run --no-sync pytest -m live -q` (Ollama, Claude, Jev).
2. On the laptop: `make bench` (Qwen 3.6 vs 3.8, optionally the MLX tags and oMLX); paste the
   table into the README.
3. A full 15-minute run in the browser with a real target vacancy and the owner's CV (M1/M2
   acceptance). Check every page: upload, briefing, interview, review, PDF download, practice.
4. `coach usage <run>` → fill the README metrics table (local share, escalations, cost,
   latency).
5. Tune the first-draft prompts (`prompts/`) and Jev criteria (`app/judgments/catalog.py`,
   bump `version` on change) based on what the real run shows.
6. Spoken answers: build with `--build-arg WITH_SPEECH=1`, measure a 1-minute answer (M5: under
   20 s within the CPU cap). If too slow: propose raising the cap during transcription or
   transcribing on the laptop; ask the owner.

### Phase 3: evaluation
The owner writes `eval/set/*.jsonl` (format in `eval/README.md`); `make eval` → thresholds into
`config/thresholds.yaml`; add `TYPESAFE_API_KEY` as a GitHub Actions secret for the CI subset.

### Phase 4: public release
1. Owner decisions (below), then a final secret and personal-data scan of the whole history
   (`git log -p | grep -nE '...'`), because making the repo public exposes all commits.
2. README: real metrics, screenshots (with fake or anonymised data), link to `docs/deploy.md`.
3. `gh repo edit --visibility public --accept-visibility-change-consequences`.

## 5. Owner decisions still open
- ~~License~~: **MIT** (`LICENSE`, 2026-09-27; holder "the Interview Simulator contributors").
- ~~Personal content~~: `docs/scope.md` and the other docs were anonymised on 2026-09-27
  (no owner name, employer or target organisation). **The git history still contains the
  original text** (commits before the anonymisation). Before making the repo public, the owner
  chooses: (a) accept that, (b) rewrite history (`git filter-repo`, then force-push `main`), or
  (c) publish a fresh repository with a single squashed initial commit. Recommended: (c).
  Also: two existing commits (the initial commit and the merge of PR #1) carry the owner's
  **work e-mail address** as author/committer, which (b) or (c) removes as well. For new
  commits, set a private address first:
  `git config user.email "<id>+<username>@users.noreply.github.com"` (GitHub → Settings →
  Emails → "Keep my email addresses private"), and use "Squash and merge" or merge locally
  so GitHub does not record the work address on merge commits.
- D5 data policy check (`docs/privacy.md`), speaking targets, whisper size and location,
  budget caps (`config/models.yaml`), USD→EUR rate. See `docs/next-steps.md`.

## 6. Known risks and unverified assumptions
| Item | Status |
|---|---|
| Docker image build (Pango/HarfBuzz package names on Debian slim) | unverified |
| Container reaches the laptop via the host's Tailscale (bridge network → tailscale0) | assumed; test in phase 1 step 6 |
| `launchctl setenv OLLAMA_HOST` survives reboots | no: re-run after reboot, or use a LaunchAgent |
| Ollama JSON-schema output and `think: false` with qwen3.6 | assumed from Ollama docs; the live test checks it |
| Jev answers in production match the SDK types used | built from the docs snapshot in `docs/vendor/typesafe/` (SDK 0.7.2) |
| faster-whisper speed at 0.5 CPU | unknown; likely too slow for the 20 s target |
| SSE progress through nginx (`proxy_buffering off` block) | configured, untested |
| Prompts, personas, tips, catalog wording | first drafts; review after the first real run |
