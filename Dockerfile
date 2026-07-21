# Usar imagen base ligera de Python 3.12
FROM python:3.12-slim

# Evitar que Python escriba archivos .pyc de caché
ENV PYTHONDONTWRITEBYTECODE=1
# Evitar que Python amortigüe stdout/stderr (salida inmediata de logs)
ENV PYTHONUNBUFFERED=1

# Establecer directorio de trabajo en el contenedor
WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar el archivo de dependencias primero para optimizar la caché de capas de Docker
COPY requirements.txt /app/

# Instalar las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código fuente del proyecto
COPY . /app/

# Exponer el puerto del servidor FastAPI
EXPOSE 8003

# Comando por defecto para iniciar la aplicación mediante Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
