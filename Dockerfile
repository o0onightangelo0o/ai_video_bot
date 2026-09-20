FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY bot ./bot
RUN mkdir -p /app/data /app/logs

# Non-root user
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD sh -c 'if [ "$MODE" = "webhook" ]; then curl -fs http://localhost:${PORT:-8000}/health || exit 1; else exit 0; fi'

CMD ["python", "-m", "bot.main"]
