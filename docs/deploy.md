# Self-hosting guide

How to run Interview Coach yourself with the same setup as the reference deployment: one small
Linux server (Docker + nginx), and a Mac or PC with a GPU (or Apple Silicon) that runs the local
model. The infrastructure is open source throughout: Docker, nginx, certbot/Let's Encrypt,
Tailscale (client), Ollama, SQLite, faster-whisper. The two model APIs (Anthropic, TypeSafe) need
your own accounts.

```
browser ──https──> nginx (server) ──> app container (127.0.0.1:8090) ──> SQLite volume
                                            │  Tailscale (private network)
                                            ├──> Ollama on the model machine (Qwen + bge-m3)
                                            └──> Claude API, TypeSafe (Jev) API: pseudonymised text only
```

**Secrets rule:** the real `.env` exists only on the server, created by `deploy/init-env.sh`
with permissions 600. The repository only contains `.env.example`, with empty values and an
explanation of every variable.

## Requirements

| Machine | Needs |
|---|---|
| Server (e.g. 2 vCPU / 4–8 GB, Ubuntu 22.04+) | Docker + compose plugin, nginx, certbot, Tailscale, openssl, rsync |
| Model machine (e.g. Apple Silicon with 32 GB, or a GPU PC) | Ollama, Tailscale, ~25 GB free disk |
| Your workstation | git, [uv](https://docs.astral.sh/uv/) (runs `make check` before deploying), rsync, ssh, Pango for the PDF tests (macOS: `brew install pango`) |
| Accounts | Anthropic API key, TypeSafe API key, a (sub)domain (e.g. free DuckDNS) |

If the server already runs other services, the app stays out of their way: the container is
capped (`cpus: 0.5`, `mem_limit: 768m` in `deploy/docker-compose.yml`), listens only on
`127.0.0.1:8090`, and nginx gets one extra site file. Nothing else on the server is changed.

## 1. Private network (Tailscale)

1. Install Tailscale on the model machine and on the server; log both into the same tailnet
   (`sudo tailscale up` on the server).
2. Note the model machine's address: `tailscale ip -4` (a `100.x.y.z` address).
3. In the Tailscale admin console, restrict access so only the server can reach the model
   machine on port 11434 (ACLs / tags).

## 2. Ollama on the model machine

```bash
ollama pull qwen3.6:35b-a3b     # ~23 GB; check "100% GPU" with: ollama ps
ollama pull bge-m3
# macOS: listen on the Tailscale address only, then restart the Ollama app
launchctl setenv OLLAMA_HOST "100.x.y.z:11434"
```

On Linux, set `OLLAMA_HOST` in the ollama systemd unit instead. Ollama has no authentication:
never bind it to `0.0.0.0` on a network you do not control. Check from the server:
`curl http://100.x.y.z:11434/api/tags`.

Other models or runtimes (e.g. oMLX) are a config change in `config/models.yaml`; compare them
first with `scripts/bench_local.py`.

## 3. Code and secrets on the server

From your workstation (runs the checks, then rsyncs the repo; `.env` and data are never synced):

```bash
REMOTE_DIR=~/interview-simulator deploy/deploy.sh <user>@<server> [ssh-port]
```

The first run builds the image but the app cannot start without `.env`. On the server, in the
repo directory:

```bash
deploy/init-env.sh     # creates .env (chmod 600); generates PII_ENCRYPTION_KEY,
                       # SESSION_SECRET and HEALTH_TOKEN; opens it in nano
```

Paste `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY` and `OLLAMA_BASE_URL=http://100.x.y.z:11434`.
Back up `PII_ENCRYPTION_KEY` in a password manager. Then start the app:

```bash
cd deploy && docker compose up -d --build && docker compose ps
curl -s http://127.0.0.1:8090/healthz    # {"db":true,"local_model":true,"new_runs_allowed":true}
```

If `local_model` is false, check that the container can reach the model machine through the
host's Tailscale:
`docker compose exec app python -c "import urllib.request as u; print(u.urlopen('http://100.x.y.z:11434/api/tags').status)"`.

## 4. Domain and HTTPS (nginx + certbot)

1. Point a (sub)domain at the server's IP (DuckDNS: add a subdomain in its dashboard).
2. `sudo cp deploy/nginx-interview.conf /etc/nginx/sites-available/interview`, replace
   `INTERVIEW_DOMAIN`, then
   `sudo ln -s /etc/nginx/sites-available/interview /etc/nginx/sites-enabled/`.
3. Certificate: `sudo certbot --nginx -d <your-domain>`, then `sudo nginx -t && sudo systemctl reload nginx`.
4. Firewall: only your SSH port, 80 and 443 open.

## 5. Accounts

```bash
cd deploy
docker compose exec app uv run --no-sync coach create-admin --email you@example.com
docker compose exec app uv run --no-sync coach invite --role candidate   # prints a code
```

Log in at `https://<your-domain>/login`; admins create more invites at `/admin`.

## 6. Checks against the real providers

The default image contains runtime dependencies only. For the live smoke tests on the server,
build once with the test tools:

```bash
cd deploy
docker compose build --build-arg WITH_DEV=1 && docker compose up -d
docker compose exec app uv run --no-sync pytest -m live -q
docker compose exec app uv run --no-sync coach usage      # calls, cost, local share
```

Spoken answers need faster-whisper: build with `--build-arg WITH_SPEECH=1`.

## 7. Backups and monitoring

- Nightly encrypted backup to off-server storage, 14 days kept: see the header of
  `deploy/backup.sh` (needs `BACKUP_PASSPHRASE_FILE` and `BACKUP_REMOTE`) and add the cron line.
- Test a restore once: `deploy/restore.sh <file>.db.gpg`.
- Uptime monitor on `https://<your-domain>/healthz`. Deep check (Claude/Jev reachability, no
  tokens spent): `curl -H "X-Health-Token: <HEALTH_TOKEN>" "https://<domain>/healthz?deep=1"`.

## Updating

Run `deploy/deploy.sh <user>@<server> [port]` again. The server's `.env` and database are left
untouched.
