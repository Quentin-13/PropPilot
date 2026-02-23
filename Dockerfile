FROM python:3.11-slim

WORKDIR /app

# Dépendances système minimales
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn[standard]

# Copier le code source
COPY . .

# Créer le répertoire data si nécessaire
RUN mkdir -p /app/data /app/data/images

# Variables d'environnement par défaut (override via .env ou docker-compose)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data/agency.db \
    PORT=8000

# Initialisation de la base de données au premier démarrage
RUN python3 -c "from memory.database import init_database; init_database()" || true

EXPOSE 8000

# Serveur FastAPI par défaut
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
