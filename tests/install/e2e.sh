#!/usr/bin/env bash
# Test d'installation Docker de bout en bout, comme un utilisateur : compose.yaml démarré, puis une fausse console
# (tests/install/console) branchée sur le même réseau. Parcours : interface, réglages, mot de passe, approbation de la
# clé, test de connexion, synchronisation, recherche Typesense, redémarrage (données conservées).
#
#   tests/install/e2e.sh DOSSIER_DU_COMPOSE      (le projet Compose doit s'appeler « romkade », comme le fichier fourni)
#
# Variables : ROMKADE_PORT (défaut 8765), KEEP=1 pour laisser la pile en place à la fin.
set -euo pipefail
DIR=$(cd "${1:?dossier contenant compose.yaml}" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${ROMKADE_PORT:-8765}
API="http://localhost:$PORT/api"
compose() { docker compose --project-directory "$DIR" -f "$DIR/compose.yaml" "$@"; }
json() { python3 -c "import sys, json; d = json.load(sys.stdin); print($1)"; }
fail() { echo "ÉCHEC : $*" >&2; compose logs --tail 80 romkade >&2 || true; exit 1; }
step() { echo "== $*"; }
wait_ui() {
  for _ in $(seq 1 90); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")" = 200 ] && return 0
    sleep 2
  done
  fail "l'interface ne répond pas sur le port $PORT"
}
cleanup() {
  [ "${KEEP:-0}" = 1 ] && return
  docker rm -f romkade-test-console >/dev/null 2>&1 || true
  compose down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "démarrage (docker compose up -d)"
compose up -d
wait_ui
curl -fsS "http://localhost:$PORT/" | grep -qi '<html' || fail "la page d'accueil n'est pas l'interface"

step "fausse console sur le réseau du projet"
docker build -q -t romkade-test-console "$HERE/console" >/dev/null
docker rm -f romkade-test-console >/dev/null 2>&1 || true
docker run -d --name romkade-test-console --network romkade_default --network-alias console romkade-test-console >/dev/null

step "réglages de connexion et mot de passe"
curl -fsS -X PUT "$API/settings" -H 'Content-Type: application/json' \
  -d '{"host":"console","port":22,"username":"root","auth_method":"password","roms_root":"/mnt/mmc/Roms"}' >/dev/null
curl -fsS -X PUT "$API/settings/password" -H 'Content-Type: application/json' -d '{"password":"romkade"}' >/dev/null

step "empreinte de la console, puis approbation"
FP=""
for _ in $(seq 1 15); do
  FP=$(curl -s "$API/device/host-key" | json "d.get('fingerprint', '')" 2>/dev/null || true)
  [ -n "$FP" ] && break
  sleep 2
done
[ -n "$FP" ] || fail "empreinte illisible"
echo "   $FP"
curl -fsS -X POST "$API/device/host-key/trust" -H 'Content-Type: application/json' -d "{\"fingerprint\":\"$FP\"}" \
  | json "d['trusted']" | grep -q True || fail "clé non approuvée"

step "test de connexion"
RES=$(curl -s -X POST "$API/device/test-connection")
echo "$RES" | json "d['connected'] and d['sftp'] and d['roms_root_exists']" | grep -q True || fail "test de connexion : $RES"

step "synchronisation"
RUN=$(curl -fsS -X POST "$API/catalog/sync" | json "d['id']")
STATUS=running
for _ in $(seq 1 60); do
  STATUS=$(curl -fsS "$API/catalog/sync/$RUN" | json "d['status']")
  [ "$STATUS" != running ] && break
  sleep 2
done
[ "$STATUS" = completed ] || fail "synchronisation : $STATUS"
GAMES=$(curl -fsS "$API/catalog/status" | json "d['game_count']")
[ "$GAMES" -ge 4 ] || fail "$GAMES jeux au catalogue, 4 attendus"
echo "   $GAMES jeux"

step "recherche Typesense (faute de frappe tolérée)"
FOUND=""
for _ in $(seq 1 30); do
  FOUND=$(curl -fsS "$API/search?q=mrio" | json "d['engine'] + ' ' + str(d['total'])")
  case $FOUND in "typesense "[1-9]*) break ;; esac
  sleep 2
done
case $FOUND in "typesense "[1-9]*) echo "   $FOUND résultat(s)" ;; *) fail "recherche : $FOUND" ;; esac

step "redémarrage : données conservées"
compose down
compose up -d
wait_ui
curl -fsS "$API/settings" | json "d['has_password'] and d['host_key_trusted']" | grep -q True || fail "réglages perdus"
GAMES2=$(curl -fsS "$API/catalog/status" | json "d['game_count']")
[ "$GAMES2" = "$GAMES" ] || fail "catalogue perdu ($GAMES2 jeux au lieu de $GAMES)"

echo "OK : installation Docker fonctionnelle de bout en bout"
