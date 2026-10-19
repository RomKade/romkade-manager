#!/bin/bash
# Lance l'agent ROMKADE en arrière-plan, détaché : il survit à la fermeture de l'app et du menu de la console.
# Appelé par l'app ROMKADE (menu APPS) et au démarrage de la console (/mnt/mod/ctrl/autostart).
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH" HOME=/
setsid nohup python3 "$DIR/romkade_agent.py" > /dev/null 2>&1 < /dev/null &
