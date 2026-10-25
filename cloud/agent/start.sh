#!/bin/bash
# Lance l'agent ROMKADE en arrière-plan, détaché : il survit à la fermeture de l'app et du menu de la console.
# Appelé par l'app ROMKADE (menu APPS) et au démarrage de la console (/mnt/mod/ctrl/autostart).
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH" HOME=/
# Déjà lancé (au démarrage de la console) : SIGUSR1 lui fait redemander son état au cloud, sinon l'écran de
# l'app, qui attend un état écrit depuis son ouverture, afficherait « Pas de connexion au cloud ». Un agent
# d'avant cette version s'arrête au signal : la ligne suivante le relance.
PID=$(cat /tmp/romkade-agent.pid 2>/dev/null)
if [ -n "$PID" ] && grep -q romkade_agent "/proc/$PID/cmdline" 2>/dev/null; then
    kill -USR1 "$PID" && sleep 0.3
fi
setsid nohup python3 "$DIR/romkade_agent.py" > /dev/null 2>&1 < /dev/null &
