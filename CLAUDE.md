# CLAUDE.md — Interview Simulator (Interview Coach)

Build rules for Claude Code, derived from section 0 of `docs/scope.md` (the spec).

## How to work
- Build **milestone by milestone** (spec section 13). Don't start a milestone before the previous
  one meets its acceptance criteria.
- Anything marked **[DECISION]** in the spec is the owner's call. Ask; never pick silently.
  Decisions made so far are logged in `docs/decisions.md`.
- **Do not invent external API details.** Jev: `docs/vendor/typesafe/` (snapshot of the official
  docs; docs.typesafe.ai may be unreachable from cloud sessions). Claude: the official SDK docs.
  Ollama: the Ollama API docs. If the spec conflicts with the docs, the docs win; flag it.
- Model IDs, thresholds and prompts live in `config/` and `prompts/`, never in logic.

## Hard rules
- **Every model call goes through `app/llm/gateway.py`.** No SDK or HTTP calls to a model
  anywhere else.
- **Only `SafeText` leaves the server.** Raw user text must go through the pseudonymiser, which
  is the only code allowed to mint `PseudonymisedText`. `TrustedText` is only for developer-written
  prompt/catalog text. `tests/test_text_types.py` and `tests/test_privacy.py` enforce this.
- Roles marked `local_only` in `config/models.yaml` must stay on Ollama. When the laptop (Ollama)
  is offline, new runs are **blocked**; there is no external fallback for raw text.
- Never log prompt or response content. `model_calls` holds metadata only.
- Counting, dates and arithmetic are done in code, never by Jev.
- Pin versions: Jev model `jev-1.13.0`, `typesafe-sdk==0.7.2`. Upgrade deliberately.
- Never commit `.env` or real documents (CVs, vacancies). Tests use synthetic text.
- The app is deployed on the same server as the owner's trading bot: keep the resource limits
  in `deploy/docker-compose.yml`, and never touch the bot's files or services.

## Definition of done (every change)
```bash
uv run ruff check app tests && uv run ruff format --check app tests
uv run mypy app
uv run pytest -q                 # mocked; live checks: uv run pytest -m live
```
