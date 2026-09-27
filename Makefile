.PHONY: check test live eval eval-ci bench run web snapshots
# macOS + Homebrew: WeasyPrint (PDF reports) loads Pango from /opt/homebrew/lib, which dyld does
# not search by default. Set per command: SIP strips DYLD_* vars exported through /bin/sh.
DYLD := $(if $(wildcard /opt/homebrew/lib),DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib,)
check:            ## lint, format check, types, tests
	uv run ruff check app tests scripts eval
	uv run ruff format --check app tests scripts eval
	uv run mypy app
	$(DYLD) uv run pytest -q
test:
	$(DYLD) uv run pytest -q
live:             ## real calls to Ollama, Claude and Jev (costs a fraction of a cent)
	$(DYLD) uv run pytest -m live -q
eval:             ## full eval set against real Jev; writes eval/results/
	uv run python scripts/run_eval.py
eval-ci:
	uv run python scripts/run_eval.py --subset 10
bench:            ## local model speed benchmark (see README)
	uv run python scripts/bench_local.py --target ollama:qwen3.6:35b-a3b --target ollama:qwen3.8:27b
snapshots:        ## every page rendered with fictional data -> design/snapshots/ (see docs/design-handoff.md)
	$(DYLD) uv run pytest -m snapshot -q
web:              ## local web app on http://localhost:8000 (needs .env)
	uv run uvicorn app.main:app_factory --factory --reload
