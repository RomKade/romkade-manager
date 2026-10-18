# ROMKADE Manager : image pour macOS, Windows et Linux (Docker Desktop ou Docker Engine).
# Utilisation : compose.yaml (avec le moteur de recherche Typesense). Données et secrets : volume /data.

# 1. Interface web (React + Vite)
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. Serveur (FastAPI)
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ROMKADE_DATA_DIR=/data ROMKADE_SECRETS=file AGM_FRONTEND_DIST=/app/frontend/dist
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
RUN pip install ./backend
COPY --from=frontend /src/frontend/dist ./frontend/dist
RUN useradd --uid 1000 --create-home romkade && mkdir -p /data && chown romkade:romkade /data
USER romkade
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/catalog/status', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
