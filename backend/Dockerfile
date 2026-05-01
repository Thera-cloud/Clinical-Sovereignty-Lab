# =============================================================================
# LITTLE NATE — Backend API Server (GREEN / Orchestration-Only)
#
# Heavy ML packages (torch, opencv, mediapipe, librosa, moviepy) are
# excluded — they run on ORANGE/BLUE via remote dispatch.
# See .cursor/rules/three-node-sync-discipline.mdc
# =============================================================================
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# System dependencies — only what the orchestration layer needs.
# libsndfile1 for parselmouth; ffmpeg for Whisper STT fallback / classroom audio.
# opencv/mediapipe X11 libs (libgl1, libsm6, etc.) are removed — visual runs on BLUE.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    libmagic1 \
    libsndfile1 \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy lightweight requirements (no torch/opencv/mediapipe/librosa)
COPY requirements-light.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-light.txt

# Copy application code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY assets/ ./assets/
COPY scripts/ ./scripts/

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

# See entrypoint.sh: ensure /app/data/classroom_sessions.json exists ([]) and nate (uid 1000) can write
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

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
