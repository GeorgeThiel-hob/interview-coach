# Interview Simulator

Interview practice app that combines three kinds of model, each doing what it is best at:
a local Qwen model (private bulk work), Jev by TypeSafe (fast typed judgments with confidence),
and Claude (planning, hard cases, written feedback). Spec: [`docs/scope.md`](docs/scope.md).

Status: **M0 (foundations)**. The model gateway, its three providers, cost logging, budget caps
and the pseudonymisation guard are in place. The interview loop comes in M1.

## Development

```bash
uv sync
uv run pytest -q                     # mocked tests
cp .env.example .env                 # add keys, then:
uv run pytest -m live                # real calls to Ollama, Claude and Jev
uv run uvicorn app.main:app --reload # GET /healthz
```

On the laptop, Ollama needs the models from `config/models.yaml`:

```bash
ollama pull qwen3:30b-a3b
ollama pull bge-m3
```
