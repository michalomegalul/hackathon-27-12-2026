FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

WORKDIR /srv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH="/srv/.venv/bin:$PATH"

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY s2d ./s2d
COPY schema ./schema
COPY examples ./examples

# The HTTP API (docs/API.md). One process, because the job queue and its single worker
# thread live in it (one GPU): never run it with --workers > 1.
EXPOSE 8000
CMD ["uvicorn", "s2d.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
