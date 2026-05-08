FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

COPY etl ./etl
COPY api ./api
COPY vocabularies ./vocabularies

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "etl.extract"]
