FROM python:3.12-slim

# System deps: tzdata for APScheduler, build-essential for any C extensions in deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY app /app/app
COPY migrations /app/migrations
COPY scripts /app/scripts
COPY static /app/static

# Replace the htmx placeholder with the real library so the dashboard
# auto-refreshes out of the box for users pulling the published image.
RUN curl -fsSL https://unpkg.com/htmx.org@2.0.3/dist/htmx.min.js \
        -o /app/static/js/htmx.min.js

# Bundle the default COACH.md so first boot has a coaching manual to read.
# Lifespan hook copies it into /data/brain/ if missing.
COPY data/brain/COACH.md /app/seed/COACH.md

# Data dir is bind-mounted; create the path so the volume mount has a target
RUN mkdir -p /data/brain/daily

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
