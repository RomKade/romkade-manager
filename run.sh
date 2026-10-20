#!/bin/sh
# Lance Anbernic Game Manager sur http://127.0.0.1:8765 et ouvre le navigateur.
# L'interface (frontend/dist, hors dépôt) est compilée au premier lancement : Node 20 ou plus (brew install node).
# Pour l'installation sans Node ni Python, sur macOS, Windows et Linux : Docker (voir README).
#
#   ./run.sh               sur ce Mac seulement
#   ./run.sh --telephone   aussi depuis le téléphone, par une adresse ngrok protégée par mot de passe
#
# Mode téléphone : ngrok (compte configuré : `ngrok config add-authtoken …`) publie l'interface sur une adresse
# https. L'application n'a pas de comptes : ngrok demande donc un identifiant et un mot de passe AVANT que la
# requête n'arrive sur ce Mac (règle « basic-auth », fichier PHONE_POLICY). Le mot de passe est créé au premier
# lancement et gardé dans le dossier de données (lisible par toi seul) : le navigateur du téléphone peut le retenir.
# Le serveur n'accepte en plus de localhost que l'adresse ngrok de ce lancement (AGM_EXTRA_HOSTS).
set -e
PORT=8765
DATA="$HOME/Library/Application Support/AnbernicGameManager"
cd "$(dirname "$0")/backend"

PHONE=0
[ "$1" = "--telephone" ] && PHONE=1

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Le port $PORT est déjà utilisé par :"
  lsof -nP -iTCP:$PORT -sTCP:LISTEN
  echo
  echo "C'est sans doute une instance précédente de l'application. Pour l'arrêter :"
  echo "  kill \$(lsof -t -iTCP:$PORT -sTCP:LISTEN)"
  exit 1
fi

PY=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
if [ ! -x .venv/bin/python ]; then
  echo "Création de l'environnement Python..."
  "$PY" -m venv .venv
fi
.venv/bin/pip install -q --disable-pip-version-check -e ".[dev]"

if [ ! -f ../frontend/dist/index.html ]; then
  command -v npm >/dev/null || { echo "L'interface n'est pas encore compilée et Node est introuvable : brew install node, puis ./run.sh"; exit 1; }
  echo "Compilation de l'interface (première fois)..."
  ( cd ../frontend && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null )
fi

if [ $PHONE = 0 ]; then
  ( sleep 2 && open "http://127.0.0.1:$PORT" ) &
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT
fi

# ---------- mode téléphone ----------
command -v ngrok >/dev/null || { echo "ngrok est introuvable : brew install ngrok"; exit 1; }
mkdir -p "$DATA"
PASSWORD_FILE="$DATA/phone_password"
PHONE_POLICY="$DATA/phone_policy.yml"
USER_NAME=agm
umask 077
if [ ! -s "$PASSWORD_FILE" ]; then
  # 20 caractères sans symboles ambigus, facile à recopier une fois sur le téléphone
  LC_ALL=C tr -dc 'A-HJ-NP-Za-km-z2-9' < /dev/urandom | head -c 20 > "$PASSWORD_FILE"
fi
PASSWORD=$(cat "$PASSWORD_FILE")
cat > "$PHONE_POLICY" <<EOF
on_http_request:
  - actions:
      - type: basic-auth
        config:
          credentials:
            - "$USER_NAME:$PASSWORD"
EOF

NGROK_LOG="$DATA/ngrok.log"
ngrok http "127.0.0.1:$PORT" --traffic-policy-file "$PHONE_POLICY" --log=stdout > "$NGROK_LOG" 2>&1 &
NGROK_PID=$!
trap 'kill $NGROK_PID 2>/dev/null' EXIT INT TERM

# Le tunnel vers CE port : un autre ngrok déjà lancé (autre projet) prend la console locale 4040, le nôtre passe
# alors sur 4041, 4042…
URL=""
for _ in $(seq 1 30); do
  for API in 4040 4041 4042 4043; do
    URL=$(curl -s "http://127.0.0.1:$API/api/tunnels" 2>/dev/null \
      | .venv/bin/python -c "import sys, json; t = json.load(sys.stdin).get('tunnels', []); print(next((x['public_url'] for x in t if x['public_url'].startswith('https') and x.get('config', {}).get('addr', '').endswith(':$PORT')), ''))" 2>/dev/null || true)
    [ -n "$URL" ] && break
  done
  [ -n "$URL" ] && break
  kill -0 $NGROK_PID 2>/dev/null || break
  sleep 0.5
done
if [ -z "$URL" ]; then
  echo "ngrok n'a pas démarré. Journal : $NGROK_LOG"
  tail -5 "$NGROK_LOG"
  exit 1
fi

echo
echo "  Game Manager sur le téléphone"
echo "  ─────────────────────────────"
echo "  Adresse      : $URL"
echo "  Identifiant  : $USER_NAME"
echo "  Mot de passe : $PASSWORD"
echo "  (ngrok affiche d'abord une page d'avertissement : « Visit Site »)"
echo
.venv/bin/python -c "import segno, sys; segno.make(sys.argv[1], error='m').terminal(compact=True)" "$URL" 2>/dev/null || true
echo
echo "  Ctrl+C arrête le serveur et l'accès depuis le téléphone."
echo

( sleep 2 && open "http://127.0.0.1:$PORT" ) &
AGM_EXTRA_HOSTS="${URL#https://}" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT
