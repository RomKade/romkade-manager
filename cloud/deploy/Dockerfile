# Serveur ROMKADE Cloud (MCP + relais des consoles). © 2026 ROMKADE, tous droits réservés.
# Contexte de construction : la racine du dépôt (backend/ du Manager + cloud/server/).
FROM python:3.13-slim
# PYTHONPATH : le module du Manager (app) est lu depuis ses sources, avec ses bases (app/data/*.json.gz) que
# l'installation par pip ne copie pas.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/srv/backend:/srv/cloud/server \
    ROMKADE_CLOUD_DB=/data/cloud.sqlite3 ROMKADE_DATA_DIR=/data
WORKDIR /srv
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
COPY cloud/server/pyproject.toml cloud/server/pyproject.toml
COPY cloud/server/romkade_cloud cloud/server/romkade_cloud
RUN pip install ./backend ./cloud/server \
    && useradd --system --uid 10001 --home /data romkade && mkdir -p /data && chown romkade /data
USER romkade
WORKDIR /srv/cloud/server
VOLUME ["/data"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/healthz',timeout=4)"
CMD ["python", "-m", "romkade_cloud", "serve", "--host", "0.0.0.0", "--port", "8787"]
