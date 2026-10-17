#!/bin/sh
# Lance un jeu sur Onion OS (Miyoo Mini / Mini Plus), envoyé par SSH (sh de BusyBox, pas de bash).
#
#   $1 = chemin complet de la ROM (/mnt/SDCARD/Roms/GBA/jeu.zip)    $2 = « run » : étape détachée (interne)
#
# Copié dans /tmp/agm-onion-launch.sh (mémoire vive) par Game Manager, qui le lance avec sh : rien n'est écrit sur
# la carte.
# Onion tourne en boucle (/mnt/SDCARD/.tmp_update/runtime.sh) : le menu (MainUI) écrit la commande du jeu choisi
# dans /tmp/cmd_to_run.sh puis se ferme ; la boucle la range dans .tmp_update/cmd_to_run.sh et lance le jeu.
# On fait pareil : commande au format de MainUI (émulateur de Emu/<console>/config.json), puis fermeture du
# menu comme le fait Onion (pkill -2 MainUI). Un jeu ou une appli ouverte est d'abord quitté (RetroArch : QUIT,
# sauvegarde automatique comprise), le temps que le menu revienne.
SD=/mnt/SDCARD
LOG=/tmp/agm-launch.log
ROM="$1"

if [ "$2" != "run" ]; then
    [ -d "$SD/.tmp_update" ] || { echo no-onion; exit 7; }
    [ -f "$ROM" ] || { echo no-rom; exit 6; }
    rel=${ROM#"$SD"/Roms/}
    dir=${rel%%/*}
    emu=""
    for c in "$SD"/Emu/*/config.json; do
        grep -q "\"rompath\":[[:space:]]*\"\.\./\.\./Roms/$dir\"" "$c" && { emu=$(dirname "$c"); break; }
    done
    [ -n "$emu" ] || { echo "no-emu $dir"; exit 5; }
    launch=$(sed -n 's/.*"launch":[[:space:]]*"\([^"]*\)".*/\1/p' "$emu/config.json" | head -1)
    [ -n "$launch" ] || { echo "no-emu $dir"; exit 5; }
    printf 'LD_PRELOAD=%s/miyoo/app/../lib/libpadsp.so "%s/%s" "%s/../../Roms/%s"' "$SD" "$emu" "$launch" "$emu" "$rel" \
        > /tmp/agm-onion-cmd
    # Suite détachée : Onion coupe SSH au lancement d'un jeu (sauf « Keep services alive »).
    nohup sh "$0" "$ROM" run > "$LOG" 2>&1 < /dev/null &
    echo started
    exit 0
fi

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Descendants d'un processus (ppid lu dans /proc/<pid>/stat).
children() {
    for s in /proc/[0-9]*/stat; do
        set -- $(cat "$s" 2>/dev/null)
        [ "$4" = "$PARENT" ] && echo "$1"
    done
}
kill_tree() {
    PARENT=$1
    for c in $(children); do kill_tree "$c"; done
    kill -TERM "$1" 2>/dev/null
}

# 1. Un jeu ou une appli est ouvert : on le quitte et on attend le menu.
if ! pidof MainUI > /dev/null; then
    if pidof retroarch > /dev/null; then
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            pidof retroarch > /dev/null || break
            printf QUIT | nc -u -w1 127.0.0.1 55355 > /dev/null 2>&1
            sleep 1
        done
        pidof retroarch > /dev/null && kill -TERM $(pidof retroarch)
        log "jeu quitté"
    else
        for p in $(pgrep -f "$SD/.tmp_update/cmd_to_run.sh"); do kill_tree "$p"; done
        log "appli fermée"
    fi
    n=0
    while [ $n -lt 30 ] && ! pidof MainUI > /dev/null; do sleep 0.5; n=$((n + 1)); done
    pidof MainUI > /dev/null || { log "le menu n'est pas revenu"; exit 3; }
    sleep 1
fi

# 2. Commande du jeu, puis fermeture du menu : la boucle d'Onion lance le jeu.
cp /tmp/agm-onion-cmd /tmp/cmd_to_run.sh && sync
log "commande : $(cat /tmp/cmd_to_run.sh)"
pkill -2 MainUI
n=0
while [ $n -lt 20 ] && pidof MainUI > /dev/null; do sleep 0.5; n=$((n + 1)); done
log "menu fermé, lancement par Onion"
