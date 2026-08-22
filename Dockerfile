FROM python:3.11-slim

# Evitar buffers en logs de Python
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias fijas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del proyecto
COPY . .

# Instalar el agente en modo editable para habilitar el comando 'agente'
RUN pip install --no-cache-dir -e .

# Mantener el contenedor listo para interactuar por terminal
CMD ["agente", "chat"]