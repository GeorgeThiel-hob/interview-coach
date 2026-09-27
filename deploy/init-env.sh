#!/usr/bin/env bash
# Run ON THE SERVER, in the repo root: creates the real .env from .env.example.
# - refuses to overwrite an existing .env
# - sets permissions to 600 before anything is written into it
# - generates PII_ENCRYPTION_KEY and SESSION_SECRET (and HEALTH_TOKEN)
# - then you paste the API keys and OLLAMA_BASE_URL yourself (nano opens the file)
# Secrets are never printed to the terminal and never leave the server.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -e .env ]; then
  echo ".env already exists; edit it with: nano .env   (permissions: $(stat -c %a .env))"
  exit 1
fi
umask 077
cp .env.example .env
chmod 600 .env
fernet="$(openssl rand -base64 32 | tr '+/' '-_')"
session="$(openssl rand -base64 48 | tr -d '\n=+/')"
health="$(openssl rand -hex 24)"
sed -i "s|^PII_ENCRYPTION_KEY=.*|PII_ENCRYPTION_KEY=${fernet}|; s|^SESSION_SECRET=.*|SESSION_SECRET=${session}|; s|^HEALTH_TOKEN=.*|HEALTH_TOKEN=${health}|" .env
echo "Created .env (chmod 600) with generated PII_ENCRYPTION_KEY, SESSION_SECRET and HEALTH_TOKEN."
echo "Now paste ANTHROPIC_API_KEY, TYPESAFE_API_KEY and OLLAMA_BASE_URL."
echo "Back up PII_ENCRYPTION_KEY in your password manager (grep PII_ENCRYPTION_KEY .env)."
if [ -t 0 ]; then "${EDITOR:-nano}" .env; fi
