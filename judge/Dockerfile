FROM python:3.11-slim

# Evitar buffers en logs de Python
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# curl es necesario para el healthcheck definido en docker-compose.yml
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias del judge (minimas)
COPY judge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar solo el paquete judge para mantener la imagen pequena
COPY judge/ ./judge/

EXPOSE 8000

CMD ["uvicorn", "judge.app:app", "--host", "0.0.0.0", "--port", "8000"]
