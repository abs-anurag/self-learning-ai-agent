FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg, asyncpg, and pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY alembic.ini /app/alembic.ini

# Expose port for FastAPI
EXPOSE 8000

# Default command: run FastAPI via uvicorn
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
