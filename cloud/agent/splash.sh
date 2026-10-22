#!/bin/bash
# Écran « app ROMKADE installée / mise à jour » (screen.py --splash), lancé par le Manager juste après
# l'installation. © 2026 ROMKADE, tous droits réservés.
#
#   $1 = installed | updated   $2 = durée en secondes (6 par défaut)
#
# Le menu de la console (dmenu.bin) s'affiche sur sa propre couche, au-dessus de l'écran où dessine l'app : il faut
# le fermer, comme pour un jeu lancé par le Manager (backend/app/device/launch.sh). On met en pause la boucle qui le
# relance, on le ferme proprement (SIGINT), on affiche l'écran, puis on relâche la boucle : le menu revient seul.
# Le trap garantit ce retour, même si l'écran échoue.

KIND="${1:-updated}"
DURATION="${2:-6}"
HERE="$(cd "$(dirname "$0")" && pwd)"
LOOP_CMD="/bin/bash /mnt/vendor/ctrl/loadapp.sh"
MENU_LOOP_CMD="/bin/bash /mnt/vendor/ctrl/dmenu_ln"

log() { echo "[$(date +%T)] $*"; }

close_menu() {
    kill -INT "$1" 2>/dev/null
    for _ in $(seq 1 25); do [ -d "/proc/$1" ] || return 0; sleep 0.2; done
    log "menu $1 forcé"; kill -9 "$1" 2>/dev/null
}

# PID des processus dont la ligne de commande est exactement "$1" (jamais par motif : voir launch.sh).
pids_of_cmd() {
    local d
    for d in /proc/[0-9]*; do
        [ "$( { tr '\0' ' ' < "$d/cmdline"; } 2>/dev/null)" = "$1 " ] && echo "${d#/proc/}"
    done
}

for _ in $(seq 1 50); do pidof dmenu.bin >/dev/null && break; sleep 0.2; done
LOOP=$(pids_of_cmd "$LOOP_CMD" | head -1)
[ -n "$LOOP" ] || { log "boucle du menu introuvable"; exit 4; }
trap 'kill -CONT "$LOOP" 2>/dev/null; log "menu relâché"' EXIT
kill -STOP "$LOOP"
for p in $(pidof dmenu.bin); do close_menu "$p"; done
# dmenu_ln attend 30 s après un menu fermé par signal : on le ferme, avec son « sleep ».
for p in $(pids_of_cmd "$MENU_LOOP_CMD"); do pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; done

log "écran $KIND"
python3 "$HERE/screen.py" --splash "$KIND" "$DURATION"
