# Dockerfile - judge

FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y gcc

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:latest /uvx /usr/local/bin/uvx

WORKDIR /src

COPY pyproject.toml uv.lock ./
RUN uv sync --group judge --locked

COPY config.py .
COPY shared ./shared
COPY judge ./judge

FROM python:3.12-slim

WORKDIR /src
COPY --from=builder /src /src

CMD [".venv/bin/python3", "-m", "judge.run"]