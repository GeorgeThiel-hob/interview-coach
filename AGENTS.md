# AGENTS.md

Instructions for AI coding agents (Cursor, Claude Code, Codex, ...) working in this repo.

1. Read `CLAUDE.md` (build rules and hard rules) and `docs/HANDOFF.md` (current state, rules
   for working on a deployment, open work) before doing anything.
2. The spec is `docs/scope.md`; decisions are logged in `docs/decisions.md`.
3. Never create, print or commit secrets. The repo keeps `.env.example` with empty values; a
   real `.env` is git-ignored (on a server it is created by `deploy/init-env.sh`, locally as in
   `docs/getting-started.md`).
4. The deployment server is shared with other services: only touch this app's own files,
   container and nginx site. Ask the owner before any `sudo`, package install, or change
   outside the app's directory.
5. Definition of done: `make check` passes (lint, format, types, tests).
