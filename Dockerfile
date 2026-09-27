FROM python:3.12-slim

# WeasyPrint (PDF reports) needs Pango and fonts from the OS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

# WITH_DEV=1: also install test tools (pytest -m live on the server).
# WITH_SPEECH=1: install faster-whisper for spoken answers.
ARG WITH_DEV=0
ARG WITH_SPEECH=0
ENV UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN groups=""; [ "$WITH_DEV" = 1 ] && groups="$groups --group dev"; [ "$WITH_SPEECH" = 1 ] && groups="$groups --group speech"; \
    [ "$WITH_DEV" = 1 ] || groups="$groups --no-dev"; \
    uv sync --locked --no-install-project $groups
COPY app ./app
COPY config ./config
COPY prompts ./prompts
COPY knowledge ./knowledge
COPY tests ./tests
COPY eval ./eval
COPY scripts ./scripts
RUN groups=""; [ "$WITH_DEV" = 1 ] && groups="$groups --group dev"; [ "$WITH_SPEECH" = 1 ] && groups="$groups --group speech"; \
    [ "$WITH_DEV" = 1 ] || groups="$groups --no-dev"; \
    uv sync --locked $groups && mkdir -p data && useradd --uid 10001 app && chown app data
USER app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
