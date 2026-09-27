# AGENTS.md

Instructions for AI coding agents (Cursor, Claude Code, Codex, ...) working in this repo.

1. Read `CLAUDE.md` (build rules and hard rules) and `docs/HANDOFF.md` (current state, the
   owner's wishes, and the next phases) before doing anything.
2. The spec is `docs/scope.md`; decisions are logged in `docs/decisions.md`.
3. Never create, print or commit secrets. The real `.env` exists only on the server
   (`deploy/init-env.sh`); the repo keeps `.env.example` with empty values.
4. The deployment server is shared with other services: only touch this app's own files,
   container and nginx site. Ask the owner before any `sudo`, package install, or change
   outside the app's directory.
5. Definition of done: `make check` passes (lint, format, types, tests).
