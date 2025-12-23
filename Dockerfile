# Multi-stage Dockerfile for OctoHub
# Stage 1: Builder - Install dependencies
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    postgresql-dev \
    libffi-dev

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
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_SECRET_KEY="" \
    AUTH_DATABASE_URL="sqlite:////app/data/auth.db" \
    ADMIN_USERNAME="admin" \
    ADMIN_PASSWORD="admin" \
    ADMIN_EMAIL="admin@localhost" \
    WEBHOOK_SECRET="" \
    WEBHOOK_IP_WHITELIST="" \
    SESSION_TIMEOUT_MINUTES="60" \
    CSRF_TIME_LIMIT_SECONDS="3600" \
    SESSION_COOKIE_SECURE="true"

# Create directories for data persistence
RUN mkdir -p /app/data /app/logs && \
    chown -R octohub:octohub /app/data /app/logs

# Switch to non-root user
USER octohub

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/login', timeout=5)" || exit 1

# Run with Waitress WSGI server
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=5000", "--threads=8", "wsgi:application"]
