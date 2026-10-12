# Halloween Projection Control - Dockerfile
FROM python:3.12-slim

# Omgevingsvariabelen voor Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Veilige niet-root gebruiker aanmaken (UID 1000 voor volume mount compatibiliteit)
RUN (groupadd -g 1000 appuser 2>/dev/null || groupadd appuser) && \
    (useradd -u 1000 -g 1000 -s /bin/bash -m appuser 2>/dev/null || useradd -s /bin/bash -m appuser)

# Systeempakketten installeren (ffmpeg voor video-optimalisatie en faststart)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

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
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8088/health', timeout=3).getcode() == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088", "--proxy-headers", "--forwarded-allow-ips=*"]
