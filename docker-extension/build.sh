#!/bin/sh
# Construit l'extension Docker Desktop de ROMKADE Manager, et l'installe (ou la met à jour) dans Docker Desktop.
#
#   ./build.sh                 image romkade/romkade-manager-extension:dev, interface sur le port 8765
#   ./build.sh --port 8766     à côté d'un Manager déjà lancé sur 8765 (./run.sh)
#   ./build.sh --no-install    construit seulement
#   ./build.sh --manager-image romkade-manager:main
#                              un Manager construit en local, au lieu de la dernière version publiée
#
# Docker Desktop > Settings > Extensions > « Enable Docker Extensions » doit être coché.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG="${TAG:-romkade/romkade-manager-extension:dev}"
PORT=8765
INSTALL=1
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-install) INSTALL=0; shift ;;
    --manager-image) MANAGER="$2"; shift 2 ;;
    *) echo "option inconnue : $1"; exit 1 ;;
  esac
done

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
cp -R "$HERE/Dockerfile" "$HERE/metadata.json" "$HERE/romkade.png" "$HERE/ui" "$BUILD/"
cp "$HERE/romkade.png" "$BUILD/ui/romkade.png"
sed -e "s/127.0.0.1:8765:8765/127.0.0.1:$PORT:8765/" \
    -e "s#ghcr.io/romkade/romkade-manager:latest#${MANAGER:-ghcr.io/romkade/romkade-manager:latest}#" \
    "$HERE/docker-compose.yaml" > "$BUILD/docker-compose.yaml"
printf 'window.ROMKADE_PORT = %s;\n' "$PORT" > "$BUILD/ui/config.js"

docker build -t "$TAG" "$BUILD"
[ "$INSTALL" = 1 ] || exit 0
if docker extension ls | grep -q "${TAG%:*}"; then
  docker extension update -f "$TAG"
else
  docker extension install -f "$TAG"
fi
echo "extension installée : Docker Desktop > Extensions > ROMKADE (http://localhost:$PORT)"
