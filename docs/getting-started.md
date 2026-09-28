# Getting started: run Interview Coach on your own machine

This guide runs everything on one computer: the web app, the database and the local model. It
takes about 30 minutes, most of it downloading the model. To put the app on a server so you can
use it from anywhere (and keep the model on your own computer), continue with
[deploy.md](deploy.md) afterwards.

## 1. What you need

| | |
|---|---|
| A computer that can run the local model | Apple Silicon with 32 GB memory, or a Linux/Windows PC with a GPU with 24 GB+ (see [models.md](models.md#hardware-for-the-local-model) for smaller options) |
| Disk | ~30 GB free (models, dependencies) |
| [git](https://git-scm.com) | to clone the repository |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | installs Python 3.12 and all packages (`brew install uv` on macOS) |
| [Ollama](https://ollama.com/download) | runs the local model |
| Pango | text layout for the PDF report: `brew install pango` (macOS) or `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0` (Debian/Ubuntu) |
| An **Anthropic** API key | [console.anthropic.com](https://console.anthropic.com): plan, briefing and feedback (optional, see [running without Claude](models.md#running-without-claude-fully-local-writing)) |
| A **TypeSafe** API key | [console.typesafe.ai](https://console.typesafe.ai): the Jev judge (required) |

A 15-minute practice run costs about €0.13–0.20 in API calls ([measured](models.md#costs-measured)).
Set a monthly limit in both consoles if you want a hard cap; the app also enforces its own
budget per run and per day.

## 2. Get the code and the packages

```bash
git clone https://github.com/GeorgeThiel-hob/interview-coach.git
cd interview-coach
uv sync            # creates .venv with Python 3.12 and every dependency from uv.lock
```

## 3. Download the local models

```bash
ollama pull qwen3.6:35b-a3b     # ~23 GB
ollama pull bge-m3              # ~1.2 GB
ollama ps                       # after a first request: should show "100% GPU"
```

Ollama listens on `http://localhost:11434` by default, which is what the local setup uses.

## 4. Configure `.env`

Every setting is listed, empty and explained, in `.env.example`.

```bash
cp .env.example .env
chmod 600 .env
```

Open `.env` and fill in:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `TYPESAFE_API_KEY` | your TypeSafe key |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `PII_ENCRYPTION_KEY` | output of `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SESSION_SECRET` | output of `openssl rand -hex 32` |
| `SECURE_COOKIES` | `false` (only for local http; keep `true` behind https) |

Keep a copy of `PII_ENCRYPTION_KEY` somewhere safe: stored runs use it to show real names. Never
commit `.env`; it is in `.gitignore`.

## 5. Check that everything works

```bash
make check      # lint, types and ~50 tests with fake models: no keys needed
make live       # three tiny real calls to Ollama, Claude and Jev (a fraction of a cent)
```

`make live` should report `3 passed`. If the Ollama test fails, check that Ollama is running and
the model name matches `config/models.yaml`.

On macOS the Makefile points the PDF library at Homebrew's Pango. When you run `uv run ...`
commands yourself and the PDF step fails with `cannot load library 'libgobject-2.0-0'`, first
run `export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

## 6. Start the web app

```bash
uv run coach create-admin --email you@example.com   # asks for a password (min. 10 characters)
make web                                            # http://localhost:8000
```

Log in, click **New run**, upload a vacancy and your CV, pick 15 minutes, and start. Want to try
it without your own documents first? Use the fictional vacancy and CV in `demo/source/`, with the
answer sheet as a script.

A run goes through: **preparing** (~3 minutes, live progress) → **briefing** → **interview**
(questions one at a time, follow-ups based on your answers) → **review** (scores, coverage,
feedback with sources, practice plan) → **PDF** (with the data embedded; upload it with your next
run to practise your weak points again).

Invite other people from **Admin** (invite codes), or on the command line:
`uv run coach invite --role candidate`.

## 7. Or use the command line

The same pipeline without the web UI:

```bash
uv run coach run --vacancy vacancy.pdf --cv cv.pdf --lang nl --length 15
uv run coach resume <run-id>           # continue a paused interview
uv run coach usage <run-id>            # calls, cost, local share, latency
```

Reports are written to `reports/` (PDF and JSON).

## Spoken answers (optional)

Spoken answers are transcribed with [faster-whisper](https://github.com/SYSTRAN/faster-whisper):

```bash
uv sync --group speech
```

The "Spoken" option appears once it is installed. Measured on a 0.5-CPU / 768 MB server
container, the `small` model ran out of memory and `base` needed 25 s for a 55 s answer with
weak recognition of technical terms, so give transcription more memory and CPU than that, or run
it on the model machine. `WHISPER_MODEL` selects the size.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "The local model is offline" and new runs are blocked | Ollama is not reachable at `OLLAMA_BASE_URL`; start Ollama, check `curl $OLLAMA_BASE_URL/api/tags` |
| Login works but you are logged out immediately | `SECURE_COOKIES=true` on plain http; set it to `false` locally |
| PDF download fails on macOS | Pango not found: `brew install pango`, and see the note in step 5 |
| Preparation fails at "pseudonymising" | the local model is too slow or ran out of memory; check `ollama ps`, try a smaller model |
| `make live` fails on Claude or Jev | key missing or wrong in `.env`; the error names the provider |
