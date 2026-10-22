#!/bin/sh
# Déploie ROMKADE Cloud sur la droplet (hôte SSH « do-deployer ») : sources, image, conteneur.
# La route Caddy (caddy.site, vers APISIX) s'ajoute une fois, à la main ou avec l'aide de Claude (voir README).
set -e
cd "$(dirname "$0")/../.."
DEST=app/romkade-cloud
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude tests --exclude '*.egg-info' \
  --exclude .DS_Store --exclude '.env*' --relative backend/pyproject.toml backend/app cloud/server/pyproject.toml \
  cloud/server/romkade_cloud cloud/deploy do-deployer:$DEST/
ssh do-deployer "cd $DEST/cloud/deploy && docker compose up -d --build"
