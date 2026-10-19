#!/bin/bash
# App ROMKADE (menu APPS de la console) : démarre l'agent, le fait démarrer avec la console, puis affiche
# le code d'appairage (à donner à ChatGPT, Claude…) ou l'état de la connexion.
AGENT=/mnt/mmc/romkade
STATUS=/tmp/romkade-status.json
AUTOSTART=/mnt/mod/ctrl/autostart
LINE="[ -x $AGENT/start.sh ] && $AGENT/start.sh  # ROMKADE"

show() { /mnt/mod/ctrl/printstr "$1"; }

[ -f "$AGENT/romkade_agent.py" ] || { show "ROMKADE\n\nAgent introuvable : copie le dossier « romkade » à la racine de la carte."; exit 1; }

# Démarrage avec la console : une ligne dans le script de démarrage du Stock OS Mod (retirée par uninstall.sh).
if [ -f "$AUTOSTART" ] && ! grep -qF "# ROMKADE" "$AUTOSTART"; then
    sed -i "/^exit 0$/i $LINE" "$AUTOSTART"
fi

START=$(date +%s)
"$AGENT/start.sh"

# Attend que l'agent ait parlé au cloud (20 s au plus).
for _ in $(seq 1 40); do
    AT=$(python3 -c "import json;print(int(json.load(open('$STATUS')).get('at',0)))" 2>/dev/null || echo 0)
    [ "$AT" -ge "$START" ] && break
    sleep 0.5
done

read -r PAIRED CODE NAME ONLINE < <(python3 - "$STATUS" <<'PY' 2>/dev/null
import json, sys
try:
    s = json.load(open(sys.argv[1]))
except Exception:
    s = {}
print(int(bool(s.get("paired"))), s.get("code") or "-", (s.get("name") or "-").replace(" ", "_"), int(bool(s.get("online"))))
PY
)

if [ "$ONLINE" != "1" ]; then
    show "ROMKADE\n\nPas de connexion au cloud ROMKADE.\n\nVérifie que le Wi-Fi est activé, puis rouvre l'app."
elif [ "$PAIRED" = "1" ]; then
    show "ROMKADE\n\nConsole connectée : ${NAME//_/ }\n\nDemande à ChatGPT ou Claude :\n« Quels jeux de Mega Drive j'ai ? »\n« Lance Sonic sur ma console »"
else
    show "ROMKADE\n\nCode d'appairage :\n\n        $CODE\n\nDans ChatGPT ou Claude, avec le connecteur ROMKADE :\n« Connecte ma console, code $CODE »\n\n(valable 15 minutes)"
fi
