#!/bin/sh
# Démarre les consoles du labo (ports SSH sur 127.0.0.1) puis, avec « test », lance les tests d'intégration.
# Les images de base (agm-lab/<système>-base) se construisent avec ./build-base.sh (téléchargement officiel).
set -e
cd "$(dirname "$0")"
start() {  # nom port
  docker build -q --platform linux/arm64 -t "agm-lab/$1" -f "$1/Dockerfile" . >/dev/null
  docker rm -f "agm-lab-$1" >/dev/null 2>&1 || true
  docker run -d --name "agm-lab-$1" --platform linux/arm64 -p "127.0.0.1:$2:22" "agm-lab/$1" >/dev/null
  echo "agm-lab-$1 : ssh root@127.0.0.1 -p $2"
}
for s in ${SYSTEMS:-rocknix knulli}; do
  case $s in rocknix) start rocknix 2231 ;; knulli) start knulli 2232 ;; esac
done
sleep 6
if [ "$1" = test ]; then
  cd ../backend && AGM_SYSTEMS_LAB=1 .venv/bin/python -m pytest -q tests/test_systems_lab.py
fi
