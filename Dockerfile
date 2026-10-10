# Halloween Projection Control - Dockerfile
FROM python:3.12-slim

# Omgevingsvariabelen voor Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Veilige niet-root gebruiker aanmaken
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Dependencies installeren
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Applicatiecode kopiëren
COPY app /app/app
COPY config /app/config
COPY media /app/media

# Maprechten instellen voor persistente opslag
RUN mkdir -p /app/media/background /app/media/effects /app/media/audio /app/config && \
    chown -R appuser:appuser /app

# Schakel over naar niet-root gebruiker
USER appuser

EXPOSE 8088

# Healthcheck met python urllib (geen externe curl vereist)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8088/api/status', timeout=3).getcode() == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
