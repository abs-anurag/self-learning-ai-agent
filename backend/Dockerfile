FROM python:3.12-slim AS builder

# Install system dependencies required for pgvector and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy alembic config and migrations
COPY alembic.ini .
COPY backend/db/migrations ./backend/db/migrations

# Copy only the backend source code
COPY backend/ ./backend/

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy alembic config and migrations from builder
COPY --from=builder /app/alembic.ini .
COPY --from=builder /app/backend/db/migrations ./backend/db/migrations

# Copy tests for running tests in container
COPY tests ./tests

# Copy backend source code
COPY backend/ ./backend/

# Set environment variables (defaults match .env.example)
ENV EXECUTION_MODE=demo
ENV LLM_PROVIDER=fixture
ENV POSTGRES_URL=postgresql+asyncpg://app_user:app_password@postgres:5432/agent_db
ENV REDIS_URL=redis://redis:6379/0

# Expose the API port (default uvicorn port)
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5).read()" || exit 1

# Start the FastAPI application
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]