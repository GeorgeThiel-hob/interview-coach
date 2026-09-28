# Self-hosting on a server

How to run Interview Coach on a small Linux server, reachable over https from anywhere, while the
local model keeps running on your own computer. This is the reference setup behind the public
demo. For a single-machine setup, see [getting-started.md](getting-started.md) first; this guide
assumes you have done steps 1–5 there on your computer (the "model machine").

```
browser ──https──> nginx (server) ──> app container (127.0.0.1:8090) ──> SQLite volume
                                            │  Tailscale (private network)
                                            ├──> Ollama on the model machine (Qwen + bge-m3)
                                            └──> Claude API, TypeSafe (Jev) API: pseudonymised text only
```

Why this split: the server is cheap and always on, the model machine has the memory for a
35B model, and personal data only ever travels to your own model machine, inside a private
network. When the model machine is off, finished runs stay available and new runs are blocked.

All infrastructure is open source: Docker, nginx, certbot / Let's Encrypt, Tailscale (client),
Ollama, SQLite, faster-whisper.

## Requirements

| Machine | Needs |
|---|---|
| Server (e.g. 2 vCPU / 4–8 GB, Ubuntu 22.04+) | Docker + compose plugin, nginx, certbot, Tailscale, openssl, rsync, gpg |
| Model machine | Ollama with the models from getting-started, Tailscale |
| Workstation (can be the model machine) | git, uv, rsync, ssh, Pango (for `make check`) |
| Accounts | Anthropic and TypeSafe API keys; a domain or free subdomain (e.g. [DuckDNS](https://www.duckdns.org)); a Tailscale account |

**Sharing the server with other services** is fine: the container is capped (`cpus: 0.5`,
`mem_limit: 768m` in `deploy/docker-compose.yml`), listens only on `127.0.0.1:8090`, and nginx
gets one extra site. The steps below are written so that nothing else on the server is touched:
no upgrades, no service restarts, and nginx is only ever reloaded after `nginx -t` passes.

Placeholders: `<user>` your server user, `<server>` its address, `<ssh-port>` its SSH port,
`<your-domain>` the app's domain, `100.x.y.z` a Tailscale address.

## 1. Docker on the server (as root)

Docker's official apt repository (docs.docker.com/engine/install/ubuntu):

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
NEEDRESTART_MODE=l apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker <user>
```

- `NEEDRESTART_MODE=l` makes Ubuntu's needrestart list services instead of restarting them.
- The `docker` group is equivalent to root access; it lets `deploy/deploy.sh` run
  `docker compose` without sudo. **Log in again** before `docker` works for `<user>`.
- Docker enables IP forwarding and adds its own iptables chains. The app port is published on
  `127.0.0.1` only, so Docker bypassing ufw exposes nothing.

If your hosting provider's web console mangles pasted text (some turn `:` into `;`), put the
block in a script file and run it with one short line.

## 2. Private network (Tailscale)

1. Install Tailscale on the model machine and log in.
2. On the server (as root), install it from pkgs.tailscale.com and set it up without touching
   the server's DNS, with `<user>` allowed to operate it:

   ```bash
   curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg -o /usr/share/keyrings/tailscale-archive-keyring.gpg
   curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list -o /etc/apt/sources.list.d/tailscale.list
   apt-get update && NEEDRESTART_MODE=l apt-get install -y tailscale
   tailscale set --accept-dns=false
   tailscale set --operator=<user>
   ```

   (Replace `noble` with your Ubuntu codename.) Then, as `<user>`:
   `tailscale up --accept-dns=false --operator=<user>` and open the login link it prints.
3. **Restrict access** (Tailscale admin console → Access controls): only the server may reach
   the model machine, and only on the Ollama port.

   ```json
   {
     "tagOwners": { "tag:server": ["autogroup:admin"] },
     "hosts": { "modelmachine": "100.x.y.z" },
     "grants": [
       {"src": ["autogroup:member"], "dst": ["autogroup:self"], "ip": ["*"]},
       {"src": ["tag:server"], "dst": ["host:modelmachine"], "ip": ["tcp:11434"]}
     ]
   }
   ```

   Then tag the server: Machines → the server → Edit ACL tags → `tag:server`. Tagged devices
   also do not expire, which suits a server. Your own devices keep reaching each other.

## 3. Ollama on the model machine, reachable over Tailscale

Ollama has no authentication, so bind it to the Tailscale address only (never `0.0.0.0` on a
network you do not control):

```bash
# macOS (Ollama app)
launchctl setenv OLLAMA_HOST "$(tailscale ip -4):11434"
# then quit Ollama from the menu bar and start it again
```

On Linux, set `Environment="OLLAMA_HOST=100.x.y.z:11434"` in the ollama systemd unit
(`systemctl edit ollama`) and restart it.

- `launchctl setenv` does not survive a reboot: run it again (and restart Ollama) after
  rebooting, or create a LaunchAgent that runs it at login.
- `localhost:11434` stops answering on the model machine itself; use the Tailscale address there
  too (for example in `make bench`).

Check from the server: `curl http://100.x.y.z:11434/api/tags` should list your models.

## 4. Code and secrets on the server

From your workstation, in the repository:

```bash
deploy/deploy.sh <user>@<server> <ssh-port>
```

It runs `make check`, then rsyncs the repository to `~/interview-simulator/` (never `.env`,
`data/` or local caches). On the **first** deploy there is no `.env` on the server yet, so it
stops after syncing. On the server:

```bash
cd ~/interview-simulator
deploy/init-env.sh     # creates .env (chmod 600) with generated PII_ENCRYPTION_KEY,
                       # SESSION_SECRET and HEALTH_TOKEN; prints no secrets
nano .env              # paste ANTHROPIC_API_KEY, TYPESAFE_API_KEY and
                       # OLLAMA_BASE_URL=http://100.x.y.z:11434
```

Back up `PII_ENCRYPTION_KEY` in a password manager. To check a value is set without printing
it: `grep -c '^ANTHROPIC_API_KEY=.\+' .env` (prints 1).

## 5. Build and start

Run the deploy again; now it builds the image and starts the container:

```bash
deploy/deploy.sh <user>@<server> <ssh-port>
```

On the server:

```bash
curl -s http://127.0.0.1:8090/healthz
# {"db":true,"local_model":true,"new_runs_allowed":true}
curl -s -H "X-Health-Token: $(grep '^HEALTH_TOKEN=' .env | cut -d= -f2-)" "http://127.0.0.1:8090/healthz?deep=1"
# adds "providers": {"anthropic": true, "ollama": true, "typesafe": true}  (no tokens spent)
```

If `local_model` is false, test the route from inside the container:
`docker compose -f deploy/docker-compose.yml exec app python -c "import urllib.request as u; print(u.urlopen('http://100.x.y.z:11434/api/tags').status)"`.

The build itself is not capped (the limits apply to the running container); a first build takes
a few minutes and uses more CPU than the running app.

## 6. Domain and https

1. Point a domain or subdomain at the server's IP address (DuckDNS: add a subdomain, enter the
   IP, "update ip"). A static server IP needs no update script.
2. On the server, as root:

   ```bash
   bash /home/<user>/interview-simulator/deploy/nginx-site.sh <your-domain>
   ```

   It installs `/etc/nginx/sites-available/interview` in three safe steps: an http-only site,
   then `certbot certonly --webroot` for your domain only (certbot does not edit any nginx file),
   then the https site. Every step runs `nginx -t` before a `reload`; on a failed test it puts
   the previous file back. Renewal runs through certbot's timer and reloads nginx.
3. Check: `curl -s https://<your-domain>/healthz`.
4. Firewall: only your SSH port, 80 and 443 open.

Progress pages use server-sent events; the nginx config turns buffering off for them
(`/runs/<id>/events`), so preparation steps tick off live.

## 7. Accounts

```bash
cd ~/interview-simulator/deploy
docker compose exec -it app uv run --no-sync coach create-admin --email you@example.com
docker compose exec app uv run --no-sync coach invite --role candidate   # prints a code
```

Log in at `https://<your-domain>/login`; admins create more invites at `/admin`.

## 8. The public demo page

`https://<your-domain>/demo` shows one frozen run without login (see [../demo/README.md](../demo/README.md)).
To show a link to your source code on it, add `DEMO_REPO_URL=https://github.com/<owner>/<repo>`
to `.env` and recreate the container: `docker compose -f deploy/docker-compose.yml up -d --force-recreate`.

## 9. Backups

`deploy/backup.sh` makes a consistent SQLite copy inside the container, encrypts it with gpg
(AES-256) and copies it off the server over scp; 14 days are kept. It needs any SSH/SFTP target,
for example a storage box.

```bash
# once, on the server
openssl rand -base64 48 > ~/.backup-passphrase && chmod 600 ~/.backup-passphrase
ssh-keygen -t ed25519 -f ~/.ssh/backup -N ""   # add ~/.ssh/backup.pub to the storage target
# test
BACKUP_PASSPHRASE_FILE=~/.backup-passphrase BACKUP_REMOTE=<login>@<storage-host>:interview-backups \
  ~/interview-simulator/deploy/backup.sh
# nightly (crontab -e)
15 3 * * * BACKUP_PASSPHRASE_FILE=$HOME/.backup-passphrase BACKUP_REMOTE=<login>@<storage-host>:interview-backups $HOME/interview-simulator/deploy/backup.sh >> $HOME/backup.log 2>&1
```

The script connects on port 23 (a common storage-box port; change it in the script for other
targets). Keep the passphrase in your password manager too, and test a restore once:
`deploy/restore.sh app-YYYYmmdd-HHMMSS.db.gpg`.

## 10. Updating

Run `deploy/deploy.sh <user>@<server> <ssh-port>` again. The server's `.env` and database are
left untouched. Background evaluations run inside the app, so **deploy when nobody is in the
middle of a run**; check with:

```bash
docker compose -f deploy/docker-compose.yml exec -T app /srv/.venv/bin/python -c "import sqlite3; print(sqlite3.connect('data/app.db').execute(\"select count(*) from runs where status in ('preparing','interviewing','reviewing')\").fetchone()[0])"
```

## Optional builds

| Build argument | What it adds |
|---|---|
| `BUILD_ARGS="--build-arg WITH_DEV=1" deploy/deploy.sh ...` | test tools, for `docker compose exec app uv run --no-sync pytest -m live -q` on the server |
| `BUILD_ARGS="--build-arg WITH_SPEECH=1" deploy/deploy.sh ...` | faster-whisper for spoken answers. Measured within the default caps: `small` runs out of memory, `base` takes 25 s for a 55 s answer. Raise `mem_limit` (1.5 GB+) and CPU if you enable it. The model is cached in the data volume. |

A plain `deploy/deploy.sh` builds without them again.

## Monitoring

`/healthz` is public and cheap; point an uptime monitor at `https://<your-domain>/healthz`.
`coach usage` and the admin page show calls, cost, local share, latency and escalation rates.
