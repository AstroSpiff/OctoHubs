# Multi-stage Dockerfile for OctoHubs
# Stage 1: Compile the isolated React frontend.
FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Install Python dependencies.
FROM python:3.11-alpine@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1 AS builder

# Install build dependencies
RUN apk add --no-cache \
    build-base \
    postgresql-dev \
    libjpeg-turbo-dev \
    libwebp-dev \
    zlib-dev \
    libffi-dev \
    openssl-dev \
    pkgconf \
    rust \
    cargo \
    linux-headers

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt

# Stage 3: Runtime - Minimal production image
FROM python:3.11-alpine@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1

# Install runtime dependencies only
RUN apk add --no-cache \
    libpq \
    libjpeg-turbo \
    libwebp \
    zlib \
    libffi \
    openssl \
    ca-certificates \
    tzdata && \
    addgroup -g 1000 octohubs && \
    adduser -D -u 1000 -G octohubs octohubs

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set working directory
WORKDIR /app

# Copy application files
COPY --chown=octohubs:octohubs . .

# Copy only compiled browser assets into the production image.
COPY --from=frontend-builder --chown=octohubs:octohubs /frontend/dist /app/frontend/dist

# Set environment variables
# Default paths match docker-compose.yml volume mappings
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OCTOHUBS_CONFIG_DIR="/config" \
    ADMIN_USERNAME="" \
    ADMIN_EMAIL="" \
    WEBHOOK_IP_WHITELIST="" \
    SESSION_TIMEOUT_MINUTES="60" \
    CSRF_TIME_LIMIT_SECONDS="3600" \
    SESSION_COOKIE_SECURE="true"

# Create the only application-managed persistent directory.
RUN mkdir -p /config && chown -R octohubs:octohubs /config

RUN chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER octohubs

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/health/ready', timeout=5).read()" || exit 1

# Run with Uvicorn ASGI server
# Using single worker for SSE compatibility, relying on async for concurrency
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "asgi:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "1", "--timeout-keep-alive", "300", "--ws-max-size", "1048576", "--ws-max-queue", "16", "--no-proxy-headers"]
