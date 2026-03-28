FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev libgmp-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY src/ src/

EXPOSE 8080 9000

ENV API_HOST=0.0.0.0
ENV PORT=8080

CMD ["sh", "-c", "uv run agentpay start --api-port ${PORT:-8080}"]
