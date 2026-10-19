#!/bin/sh
# Prépare le paquet ROMKADE pour la carte SD (dist/sd, à copier à la racine de la carte) :
#   romkade/           l'agent, ses modules (ceux du Manager : lancement, volume, détection du firmware)
#   Roms/APPS/         l'app ROMKADE du menu de la console et son icône
#
#   ./build.sh https://adresse-du-cloud
set -e
[ -n "$1" ] || { echo "usage : ./build.sh https://adresse-du-cloud"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/../../backend/app"
OUT="$HERE/dist/sd"
rm -rf "$HERE/dist"
mkdir -p "$OUT/romkade/vendor/app/device" "$OUT/Roms/APPS/Imgs"

cp "$HERE/romkade_agent.py" "$HERE/start.sh" "$HERE/uninstall.sh" "$OUT/romkade/"
cp -R "$HERE/stubs/." "$OUT/romkade/vendor/"
cp "$APP/__init__.py" "$APP/errors.py" "$OUT/romkade/vendor/app/"
cp "$APP/device/__init__.py" "$APP/device/launcher.py" "$APP/device/volume.py" "$APP/device/systems.py" \
   "$APP/device/launch.sh" "$APP/device/onion_launch.sh" "$APP/device/players_apply.sh" "$APP/device/volume_keys.py" \
   "$OUT/romkade/vendor/app/device/"
printf '{"server": "%s"}\n' "$1" > "$OUT/romkade/agent.json"

cp "$HERE/RomKade.sh" "$OUT/Roms/APPS/ROMKADE.sh"
cp "$HERE/../server/romkade_cloud/static/icon.png" "$OUT/Roms/APPS/Imgs/ROMKADE.png"
chmod +x "$OUT/romkade/romkade_agent.py" "$OUT/romkade/start.sh" "$OUT/romkade/uninstall.sh" "$OUT/Roms/APPS/ROMKADE.sh"
echo "paquet prêt : $OUT"
