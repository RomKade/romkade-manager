#!/bin/bash
# Désinstalle l'agent ROMKADE : arrêt, retrait du démarrage automatique. Le dossier /mnt/mmc/romkade reste
# (supprime-le à la main pour oublier aussi l'appairage).
sed -i "/# ROMKADE$/d" /mnt/mod/ctrl/autostart 2>/dev/null
[ -f /tmp/romkade-agent.pid ] && kill "$(cat /tmp/romkade-agent.pid)" 2>/dev/null
rm -f /tmp/romkade-agent.pid /tmp/romkade-status.json
echo "agent ROMKADE arrêté et retiré du démarrage"
