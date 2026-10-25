#!/bin/bash
# App ROMKADE (menu APPS de la console). © 2026 ROMKADE, tous droits réservés.
# Démarre l'agent, le fait démarrer avec la console, puis affiche l'écran ROMKADE (screen.py) : code
# d'appairage à donner à ChatGPT, Claude…, ou console connectée. B : retour au menu.
AGENT=/mnt/mmc/romkade
AUTOSTART=/mnt/mod/ctrl/autostart
LINE="[ -x $AGENT/start.sh ] && $AGENT/start.sh  # ROMKADE"

if [ ! -f "$AGENT/romkade_agent.py" ]; then
    /mnt/mod/ctrl/printstr "ROMKADE\n\nAgent not found: copy the \"romkade\" folder to the root of the card."
    exit 1
fi

# Démarrage avec la console : une ligne dans le script de démarrage du Stock OS Mod (retirée par uninstall.sh).
if [ -f "$AUTOSTART" ] && ! grep -qF "# ROMKADE" "$AUTOSTART"; then
    sed -i "/^exit 0$/i $LINE" "$AUTOSTART"
fi

START=$(date +%s)
"$AGENT/start.sh"

if ! python3 "$AGENT/screen.py" "$START" 2> /tmp/romkade-screen.log; then
    # Écran graphique indisponible (autre modèle, Pillow absent) : texte simple du firmware.
    sleep 3
    CODE=$(python3 -c "import json;print(json.load(open('/tmp/romkade-status.json')).get('code') or '')" 2>/dev/null)
    /mnt/mod/ctrl/printstr "ROMKADE\n\nPairing code: $CODE\n\nIn ChatGPT or Claude: \"Connect my console, code $CODE\""
fi
