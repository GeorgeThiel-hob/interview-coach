#!/usr/bin/env bash
# Deploy from your laptop: sync the repo to the server and rebuild the container.
# Usage: deploy/deploy.sh user@host [ssh-port]
# The server keeps its own .env (never synced). Nothing here touches the trading bot.
set -euo pipefail
TARGET="${1:?usage: deploy/deploy.sh user@host [ssh-port]}"
PORT="${2:-22}"
REMOTE_DIR="${REMOTE_DIR:-~/interview-simulator}"
cd "$(dirname "$0")/.."
make check
rsync -az --delete -e "ssh -p $PORT" \
  --exclude .git --exclude .venv --exclude data --exclude .env --exclude reports \
  --exclude eval/results --exclude '__pycache__' --exclude .mypy_cache --exclude .pytest_cache \
  --exclude .ruff_cache --exclude .DS_Store ./ "$TARGET:$REMOTE_DIR/"
# First deploy: the server has no .env yet, so stop after syncing (see docs/deploy.md step 3).
ssh -p "$PORT" "$TARGET" "cd $REMOTE_DIR && if [ ! -f .env ]; then
    echo 'Synced. No .env on the server yet: run deploy/init-env.sh there, then deploy again.'
  else cd deploy && docker compose up -d --build && docker compose ps; fi"
