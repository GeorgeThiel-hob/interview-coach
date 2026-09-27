# Deployment: the bot server + the laptop

The app runs in Docker next to the trading bot, capped at 0.5 CPU and 768 MB so it can never
starve the bot. Qwen runs on the laptop and is reached over Tailscale. Nothing here changes the
bot's files or services; the only shared pieces are nginx (one extra site) and Docker.

## 1. Tailscale (laptop and server)

1. Install Tailscale on the laptop (Mac App Store) and on the server (`curl -fsSL
   https://tailscale.com/install.sh | sh`, then `sudo tailscale up`). Log both into the same
   tailnet.
2. Note the laptop's Tailscale IP (`tailscale ip -4`, a 100.x.y.z address).
3. In the Tailscale admin console, restrict access so that only the server may reach the
   laptop on port 11434 (ACL example in the Tailscale docs: "tagged devices").

## 2. Ollama on the laptop, reachable only over Tailscale

Ollama listens on localhost by default. Make it listen on the Tailscale address only:

```bash
launchctl setenv OLLAMA_HOST "100.x.y.z:11434"   # your laptop's Tailscale IP
# quit and restart the Ollama app, then check from the server:
curl http://100.x.y.z:11434/api/tags
```

Ollama has no login of its own, so never bind it to 0.0.0.0 on a network you do not control.

## 3. Server: files and secrets

```bash
# from the laptop (first time): copy the repo
deploy/deploy.sh botuser@SERVER 2222
# on the server:
cd ~/interview-simulator && cp .env.example .env && chmod 600 .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # PII_ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                             # SESSION_SECRET
```

`.env` on the server: `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`, `OLLAMA_BASE_URL=http://100.x.y.z:11434`,
`PII_ENCRYPTION_KEY`, `SESSION_SECRET`, `HEALTH_TOKEN` (optional), `DATABASE_URL=sqlite:///data/app.db`.
Keep a copy of `PII_ENCRYPTION_KEY` in your password manager: without it, stored runs cannot show
real names again.

Check that the container can reach the laptop through the host's Tailscale:
`docker compose -f deploy/docker-compose.yml exec app python -c "import urllib.request;
print(urllib.request.urlopen('http://100.x.y.z:11434/api/tags').status)"`.

## 4. nginx + certificate (second DuckDNS subdomain)

1. Create a second DuckDNS subdomain pointing to the server IP.
2. `sudo cp deploy/nginx-interview.conf /etc/nginx/sites-available/interview`, replace
   `INTERVIEW_DOMAIN`, symlink into `sites-enabled`, `sudo nginx -t && sudo systemctl reload nginx`.
3. `sudo certbot --nginx -d <your-subdomain>.duckdns.org`.

## 5. First admin and invites

```bash
docker compose -f deploy/docker-compose.yml exec app uv run --no-sync coach create-admin --email you@example.com
docker compose -f deploy/docker-compose.yml exec app uv run --no-sync coach invite --role candidate
```

## 6. Backups (nightly, off-server, 14 days)

Create a Hetzner Storage Box (or any SSH target), a passphrase file (`chmod 600`), then add the
cron line from `deploy/backup.sh`. Test a restore once with `deploy/restore.sh` (M6 criterion).

## 7. Monitoring

Point an uptime monitor (e.g. UptimeRobot) at `https://<domain>/healthz`. With `HEALTH_TOKEN` set,
`/healthz?deep=1` plus header `X-Health-Token` also checks Claude and Jev reachability (no tokens
spent). `local_model: false` simply means the laptop is off.

## Updating

`deploy/deploy.sh botuser@SERVER 2222` runs the checks, syncs the code and rebuilds the
container. The server's `.env` and data are never overwritten.
