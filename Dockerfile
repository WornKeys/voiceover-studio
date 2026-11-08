# syntax=docker/dockerfile:1
# The app image: Python 3.12, ffmpeg, the app and the libraries for its local models.
# CUDA comes inside the torch wheels; the host only needs the NVIDIA driver and the NVIDIA Container Toolkit
# (the AWS Deep Learning AMI has both). Built on the instance by infra/instance/update.sh.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

# ffmpeg converts browser recordings; sox is used by the qwen-tts audio helpers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg sox curl \
    && rm -rf /var/lib/apt/lists/*

# No uv download cache: it would keep another ~5 GB of wheels on the instance's disk.
ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    XDG_CACHE_HOME=/cache \
    HF_HOME=/cache/huggingface \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
# Dependencies first (a separate layer, so code changes don't reinstall torch).
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --extra gpu --no-install-project

COPY config.yaml ./
COPY voiceover_studio ./voiceover_studio
RUN uv sync --locked --no-dev --extra gpu

# Run as a normal user. /cache holds the model downloads (a host folder, kept across rebuilds).
RUN useradd --uid 10001 --create-home app && mkdir -p /cache && chown app /cache
USER app

ENV APP_HOST=0.0.0.0 APP_PORT=7860
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m \
    CMD curl -fsS http://127.0.0.1:7860/api/health || exit 1
CMD ["python", "-m", "voiceover_studio"]
