# TravelKaki image: one container runs the Telegram bot + the FastAPI app.
FROM python:3.12-slim

# Copy the uv binary from its official image (no pip install needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Put the virtual env outside /app so a bind mount can't hide it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# 1) Install dependencies first. This layer is cached until pyproject/uv.lock change,
#    so code edits rebuild fast.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 2) Then copy the app code.
COPY travelkaki ./travelkaki

# Run as a normal user, not root.
RUN useradd --create-home app
# SQLite lives in /app/data (a volume in docker-compose). The app user must own it,
# or the database can't be created. (M1, issue #6.)
RUN mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000

# Docker marks the container unhealthy if /health stops answering.
# (python is used because the slim image has no curl.)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "travelkaki.main:app", "--host", "0.0.0.0", "--port", "8000"]
