FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    time \
    coreutils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 run \
    && mkdir -p /workspace \
    && chown -R run:run /workspace

WORKDIR /workspace
USER run

CMD ["sleep", "infinity"]