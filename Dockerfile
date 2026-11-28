# Rust kernels for the detective (rust/s2d-kernels). Optional at runtime: without the library
# the Python code runs instead (s2d/rustk.py), so a failed build here is the only way to lose the speedup.
FROM rust:1-slim AS kernels
WORKDIR /build
COPY rust/Cargo.toml rust/Cargo.lock ./
COPY rust/s2d-core ./s2d-core
COPY rust/s2d-kernels ./s2d-kernels
RUN cargo build --release --locked -p s2d-kernels

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

WORKDIR /srv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH="/srv/.venv/bin:$PATH"

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY s2d ./s2d
COPY --from=kernels /build/target/release/libs2d_kernels.so ./libs2d_kernels.so
COPY schema ./schema
COPY examples ./examples

# The HTTP API (docs/API.md). One process, because the job queue and its single worker
# thread live in it (one GPU): never run it with --workers > 1.
EXPOSE 8000
CMD ["uvicorn", "s2d.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
