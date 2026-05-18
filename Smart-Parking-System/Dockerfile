# ─────────────────────────────────────────────────────────────────────────────
# Smart Parking v15 — Production Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
# Two-stage build:
#   Stage 1 (node): builds the React frontend → produces dist/
#   Stage 2 (python): runs FastAPI server, serves built frontend from dist/
#
# Usage:
#   Railway / Render / Fly.io detect this Dockerfile automatically.
#   Local testing:  docker build -t smart-parking . && docker run -p 8000:8000 smart-parking
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python server ───────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY server.py ./
COPY core/ ./core/
COPY layouts/ ./layouts/

# Copy built frontend from Stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Railway sets PORT env var; default to 8000 for local testing
ENV PORT=8000

# Expose the port (documentation; Railway uses PORT env var)
EXPOSE 8000

# Start the server
# --host 0.0.0.0  : accept connections from the container network
# --port $PORT    : Railway/Render inject this; locally defaults to 8000
# --workers 1     : single worker (in-memory state is not shared across workers)
# --timeout-keep-alive 65 : keep WebSocket connections alive through proxy idle timeouts
CMD uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 65
