# Dockerfile - api

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:latest /uvx /usr/local/bin/uvx

WORKDIR /src

COPY pyproject.toml uv.lock ./
RUN uv sync --group api --locked

COPY config.py .
COPY shared ./shared
COPY api ./api

FROM python:3.12-slim

WORKDIR /src
COPY --from=builder /src /src

CMD [".venv/bin/uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]