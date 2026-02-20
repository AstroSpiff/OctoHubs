# Multi-stage Dockerfile for OctoHub
# Stage 1: Builder - Install dependencies
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    build-base \
    postgresql-dev \
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
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime - Minimal production image
FROM python:3.11-alpine

# Install runtime dependencies only
RUN apk add --no-cache \
    libpq \
    libffi \
    openssl \
    ca-certificates \
    tzdata && \
    addgroup -g 1000 octohub && \
    adduser -D -u 1000 -G octohub octohub

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set working directory
WORKDIR /app

# Copy application files
COPY --chown=octohub:octohub . .

# Set environment variables
# Default paths match docker-compose.yml volume mappings
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SECRET_KEY="" \
    OCTOHUB_CONFIG_FILE="/config/config.json" \
    OCTOHUB_RESULTS_FILE="/storage/last_results.json" \
    AUTH_DATABASE_URL="sqlite:////storage/auth.db" \
    ADMIN_USERNAME="" \
    ADMIN_PASSWORD="" \
    ADMIN_EMAIL="" \
    WEBHOOK_SECRET="" \
    WEBHOOK_IP_WHITELIST="" \
    SESSION_TIMEOUT_MINUTES="60" \
    CSRF_TIME_LIMIT_SECONDS="3600"

# Create directories for data persistence
RUN mkdir -p /config /storage /app/logs && \
    chown -R octohub:octohub /config /storage /app/logs

RUN chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER octohub

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5050/login', timeout=5)" || exit 1

# Run with Uvicorn ASGI server
# Using single worker for SSE compatibility, relying on async for concurrency
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "asgi:fastapi_app", "--host", "0.0.0.0", "--port", "5050", "--workers", "1", "--timeout-keep-alive", "300"]
