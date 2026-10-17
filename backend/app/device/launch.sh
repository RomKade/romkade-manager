#!/bin/bash
# Lance un jeu sur la console (firmware Anbernic + « Stock OS Mod »), envoyé par SSH et exécuté détaché.
# Aucun fichier n'est écrit sur la carte : le script passe en argument, son journal va dans /tmp.
#
#   $1 = dossier de la plateforme (MD, SFC, NDS…)   $2 = chemin complet de la ROM
#   $3 = facultatif : « auto » (reprise automatique) ou numéro d'emplacement de sauvegarde instantanée
#
# Le menu tourne dans une boucle : /mnt/vendor/ctrl/loadapp.sh relance sans fin dmenu_ln, qui lance dmenu.bin.
# On met cette boucle en pause (SIGSTOP), on ferme le menu, on lance le jeu comme le fait le mod
# (random.sh / RA_launch.sh), puis on relâche la boucle (SIGCONT), qui relance le menu toute seule.
# Le trap garantit ce retour du menu, même si le jeu ne démarre pas.
#
# Attention : ce script est passé à « bash -c », son texte fait donc partie de sa propre ligne de commande
# (et de celle de ses sous-shells). On ne cherche donc jamais un processus par motif (pgrep -f) : on compare
# la ligne de commande exacte (pids_of_cmd).
#
# Le menu doit quitter proprement (SIGINT) : tué par SIGKILL, il garde la couche d'affichage du processeur
# et RetroArch échoue (« mali-fbdev: Can't create EGL window surface »). dmenu.bin ignore SIGTERM.

EMU="$1"
ROM="$2"
SLOT="$3"
CORES=/mnt/mod/ctrl/configs/CORES.txt
RA=/mnt/vendor/deep/retro/retroarch

log() { echo "[$(date +%T)] $*"; }

# Charge l'emplacement $1 dès que RetroArch fait tourner le jeu (commandes réseau, port UDP 55355).
load_slot_when_ready() {
    python3 - "$1" <<'PY'
import socket, sys, time
slot = sys.argv[1]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(0.5)
for _ in range(60):
    try:
        s.sendto(b"GET_STATUS", ("127.0.0.1", 55355))
        if b"PLAYING" in s.recv(4096):
            time.sleep(1.0)
            s.sendto(f"LOAD_STATE_SLOT {slot}".encode(), ("127.0.0.1", 55355))
            print("emplacement", slot, "chargé")
            break
    except OSError:
        pass
    time.sleep(0.5)
PY
}

# Ferme proprement un menu (SIGINT), en dernier recours SIGKILL.
close_menu() {
    kill -INT "$1" 2>/dev/null
    for _ in $(seq 1 25); do [ -d "/proc/$1" ] || return 0; sleep 0.2; done
    log "menu $1 forcé"; kill -9 "$1" 2>/dev/null
}

# PID des processus dont la ligne de commande est exactement "$1" (arguments séparés par des espaces).
pids_of_cmd() {
    local d
    for d in /proc/[0-9]*; do
        [ "$( { tr '\0' ' ' < "$d/cmdline"; } 2>/dev/null)" = "$1 " ] && echo "${d#/proc/}"
    done
}
LOOP_CMD="/bin/bash /mnt/vendor/ctrl/loadapp.sh"
MENU_LOOP_CMD="/bin/bash /mnt/vendor/ctrl/dmenu_ln"

# Environnement du menu (langue, bibliothèques), comme si le jeu était lancé par lui.
MENU_PID=$(pidof dmenu.bin | awk '{print $1}')
if [ -n "$MENU_PID" ]; then
    while IFS= read -r -d '' kv; do
        case "$kv" in LANG=*|LANGUAGE=*|LD_LIBRARY_PATH=*|PATH=*) export "$kv" ;; esac
    done < "/proc/$MENU_PID/environ"
fi
# AGM_LAUNCH : marque les jeux lancés par Game Manager (volume.py choisit ainsi le bon réglage de volume).
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-/usr/lib32:/usr/lib:/mnt/vendor/lib}" HOME=/ AGM_LAUNCH=1
cd /

[ -f "$ROM" ] || { log "ROM introuvable : $ROM"; exit 2; }

# 0. Menus orphelins (sans parent) laissés par un ancien essai : on les ferme.
for p in $(pidof dmenu.bin); do
    [ "$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null)" = 1 ] && close_menu "$p" && log "menu orphelin $p fermé"
done

# 1. Un jeu RetroArch tourne déjà : on le quitte proprement (sauvegarde auto comprise).
for _ in $(seq 1 50); do
    pidof retroarch >/dev/null || break
    echo -n QUIT > /dev/udp/127.0.0.1/55355 2>/dev/null  # commande réseau de RetroArch
    sleep 0.3
done
if pidof retroarch >/dev/null; then log "RetroArch ne se ferme pas"; exit 3; fi

# Manette de chaque joueur choisie dans Game Manager (voir app/device/players.py). RetroArch est fermé : sa
# config ne sera plus écrasée, on y remplace les lignes input_playerN_joypad_index.
PLAYERS=/.config/agm-players RACFG=/.config/retroarch/retroarch.cfg
if [ -s "$PLAYERS" ] && [ -f "$RACFG" ]; then
    sed -i '/^input_player[1-4]_joypad_index = /d' "$RACFG" && cat "$PLAYERS" >> "$RACFG"
    log "joueurs : $(grep -o '[0-9]"$' "$PLAYERS" | tr -d '"' | tr '\n' ' ')"
fi

# Volume des jeux (voir app/device/volume.py) : notre réglage « Game Manager » (/.asoundrc) fait le volume,
# celui de RetroArch reste à 0 dB. Premier jeu depuis le démarrage : le réglage naît au maximum (+12 dB), on le
# met à 0 dB (valeur 60 sur 84, de -30 à +12 dB par pas de 0,5 dB).
if grep -q agm_vol /.asoundrc 2>/dev/null && [ -f "$RACFG" ]; then
    sed -i -e 's/^audio_volume = .*/audio_volume = "0.000000"/' -e 's/^audio_mute_enable = .*/audio_mute_enable = "false"/' "$RACFG"
    VOL="name='Game Manager Playback Volume'"
    if ! env -u LD_LIBRARY_PATH amixer -c 0 cget "$VOL" >/dev/null 2>&1; then
        ( for _ in $(seq 1 100); do env -u LD_LIBRARY_PATH amixer -q -c 0 cset "$VOL" 60,60 2>/dev/null && break
          sleep 0.2; done ) &
    fi
    log "volume des jeux par Game Manager"
    # Touches Vol+ / Vol- de la console sur ce volume (app/device/volume_keys.py), le temps du jeu.
    if [ -n "$AGM_VOLKEYS" ]; then
        python3 -c "$AGM_VOLKEYS" > /tmp/agm-volkeys.log 2>&1 &
        VOLKEYS=$!
    fi
fi
# On attend que le menu soit revenu (la boucle relance dmenu_ln après un jeu).
for _ in $(seq 1 50); do pidof dmenu.bin >/dev/null && break; sleep 0.2; done

# 2. Mise en pause de la boucle du menu, puis fermeture du menu.
LOOP=$(pids_of_cmd "$LOOP_CMD" | head -1)
[ -n "$LOOP" ] || { log "boucle du menu introuvable"; exit 4; }
resume_menu() { kill -CONT "$LOOP" 2>/dev/null; log "menu relâché"; }
trap resume_menu EXIT
kill -STOP "$LOOP"
for p in $(pidof dmenu.bin); do close_menu "$p"; done
if pidof dmenu.bin >/dev/null; then log "le menu ne se ferme pas"; exit 6; fi
# dmenu_ln attend 30 s après un menu fermé par signal : on le ferme, avec son « sleep ».
for p in $(pids_of_cmd "$MENU_LOOP_CMD"); do pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; done

# Le menu passe l'écran en 1280x1024 16 bits et ne le rétablit que s'il sort de lui-même. On remet le mode
# enregistré au démarrage par le mod (configs/fb.cfg : 640x480 32 bits), sinon RetroArch ne peut pas s'afficher
# (« No EGL configs with appropriate attributes »).
FB_CFG=/mnt/mod/ctrl/configs/fb.cfg
if [ -f "$FB_CFG" ]; then
    python3 -c 'import fcntl, os, sys
fd = os.open("/dev/fb0", os.O_RDWR)
try:
    fcntl.ioctl(fd, 0x4601, bytearray(open(sys.argv[1], "rb").read()))  # FBIOPUT_VSCREENINFO
finally:
    os.close(fd)' "$FB_CFG" && log "écran remis en $(cat /sys/class/graphics/fb0/virtual_size), $(cat /sys/class/graphics/fb0/bits_per_pixel) bits"
fi

# Son des jeux vers une enceinte Bluetooth choisie dans Game Manager (voir app/device/bluetooth.py) : /.asoundrc
# envoie la sortie « default » vers l'enceinte (HOME=/ ci-dessus) ; il faut que BlueALSA tourne.
if [ -f /.asoundrc ] && grep -q agm_bt /.asoundrc; then
    pidof bluealsa >/dev/null || { setsid nohup bluealsa -p a2dp-source > /tmp/agm-bluealsa.log 2>&1 < /dev/null & sleep 1.5; }
    log "son vers l'enceinte Bluetooth"
fi

# 3. Lancement, comme runrom() de /mnt/mod/ctrl/random.sh.
CORE=$(grep -- "-${EMU}," "$CORES" | head -1 | cut -d, -f2)
log "lancement $EMU / $CORE / $ROM"
case "$EMU" in
    NDS)
        /mnt/vendor/ctrl/setNDS.sh savedir "$ROM"
        /mnt/vendor/ctrl/setNDS.sh run "$ROM"
        ;;
    OPENBOR)
        /mnt/vendor/deep/openBOR/scripts/openbor.sh "$ROM"
        /mnt/vendor/deep/openBOR/OpenBOR.dge "$ROM"
        ;;
    PSP)
        cd /mnt/vendor/deep/ppsspp/ && ./PPSSPPSDL "$ROM"
        ;;
    *)
        [ -n "$CORE" ] || { log "aucun cœur pour $EMU dans $CORES"; exit 5; }
        if [ -n "$AGM_DEBUG" ]; then  # diagnostic : RetroArch seul, bavard, sortie dans /tmp/agm-ra.log
            case "$SLOT" in [0-9]*) load_slot_when_ready "$SLOT" & ;; esac
            cd /mnt/vendor/deep/retro && "$RA" -v -c /.config/retroarch/retroarch.cfg -L "cores/$CORE" "$ROM" > /tmp/agm-ra.log 2>&1
        elif [ "$SLOT" = "auto" ]; then
            /mnt/mod/ctrl/RA_launch.sh "$CORE" "$ROM" auto
        elif [ -n "$SLOT" ]; then
            load_slot_when_ready "$SLOT" &
            /mnt/mod/ctrl/RA_launch.sh "$CORE" "$ROM"
        else
            /mnt/mod/ctrl/RA_launch.sh "$CORE" "$ROM"
        fi
        ;;
esac
CODE=$?
[ -n "$VOLKEYS" ] && kill "$VOLKEYS" 2>/dev/null
log "jeu terminé (code $CODE)"
sync
