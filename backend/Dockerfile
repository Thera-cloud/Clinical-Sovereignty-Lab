# =============================================================================
# LITTLE NATE — Backend API Server
# =============================================================================
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    libmagic1 \
    libsndfile1 \
    tesseract-ocr \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY assets/ ./assets/

# Create logs + data dirs and the non-root runtime user.
RUN mkdir -p /app/logs /app/data \
    && useradd -m -u 1000 nate \
    && chown -R nate:nate /app

# gosu lets the entrypoint fix volume ownership as root, then drop to the
# nate user before exec'ing uvicorn. This prevents PermissionError on
# /app/data/classroom_sessions.json (and friends) when a Docker named
# volume was first created/written by a root-running container — without
# this, /upload-video/init and /complete silently fail their save_json()
# calls and we lose the session record on the next restart.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

RUN printf '#!/bin/sh\nchown -R nate:nate /app/data /app/logs 2>/dev/null || true\nexec gosu nate "$@"\n' > /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

# Note: USER stays root so the entrypoint can chown; gosu drops to nate
# before exec'ing the CMD.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
