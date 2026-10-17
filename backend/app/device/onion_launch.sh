#!/bin/sh
# Lance un jeu sur Onion OS (Miyoo Mini / Mini Plus), envoyé par SSH (sh de BusyBox, pas de bash).
#
#   $1 = chemin complet de la ROM (/mnt/SDCARD/Roms/GBA/jeu.zip)    $2 = « run » : étape détachée (interne)
#
# Copié dans /tmp/agm-onion-launch.sh (mémoire vive) par Game Manager, qui le lance avec sh. Seule écriture sur la
# carte : le réglage « Keep services alive » d'Onion (Tweaks > Network), activé s'il ne l'est pas. Sans lui,
# Onion arrête SSH au lancement de chaque jeu (runtime.sh, « Kill services for maximum performance ») et Game
# Manager perd la console pendant la partie (jeu en cours, Quitter, volume).
# Onion tourne en boucle (/mnt/SDCARD/.tmp_update/runtime.sh) : le menu (MainUI) écrit la commande du jeu choisi
# dans /tmp/cmd_to_run.sh puis se ferme ; la boucle la range dans .tmp_update/cmd_to_run.sh et lance le jeu.
# On fait pareil : commande au format de MainUI (émulateur de Emu/<console>/config.json), puis fermeture du
# menu par SIGTERM (essayé sur Miyoo Mini Plus, Onion 4.3.1 : MainUI ignore SIGINT juste après son démarrage),
# SIGKILL en dernier recours. Un jeu ou une appli ouverte est d'abord quitté (RetroArch : QUIT,
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
    # Garder SSH pendant les jeux : réglage d'Onion, « .keepServicesAlive_ » (désactivé) -> « .keepServicesAlive ».
    cfg="$SD/.tmp_update/config"
    if [ ! -f "$cfg/.keepServicesAlive" ]; then
        mv -f "$cfg/.keepServicesAlive_" "$cfg/.keepServicesAlive" 2>/dev/null || touch "$cfg/.keepServicesAlive"
        sync
        echo keepalive-on
    fi
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
    sleep 2
fi

# 2. Commande du jeu, puis fermeture du menu : la boucle d'Onion lance le jeu.
cp /tmp/agm-onion-cmd /tmp/cmd_to_run.sh && sync
log "commande : $(cat /tmp/cmd_to_run.sh)"
pkill -TERM MainUI
n=0
while [ $n -lt 10 ] && pidof MainUI > /dev/null; do sleep 0.5; n=$((n + 1)); done
if pidof MainUI > /dev/null; then
    log "le menu ignore SIGTERM : SIGKILL"
    pkill -9 MainUI
fi
log "menu fermé, lancement par Onion"
