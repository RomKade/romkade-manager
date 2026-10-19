#!/bin/bash
# Écrit le choix des manettes de Game Manager dans la config de RetroArch (voir app/device/players.py).
# Lancé par Game Manager quand aucun jeu ne tourne, et par launch.sh avant chaque jeu (RetroArch fermé).
#
# /.config/agm-players : numéros de Game Manager, dans l'ordre des jsN de /proc/bus/input/devices.
# RetroArch (SDL2 avec udev) numérote autrement : les manettes triées par chemin sysfs. Avec une manette Xbox USB,
# « …/soc/5101000.ohci0… » passe avant les boutons « …/soc/soc@03000000:gpio_keys » : Xbox = 0, console = 1.
# On traduit donc chaque numéro dans l'ordre de RetroArch et on réserve en plus la manette au joueur
# (« vvvv:pppp nom », type 1 = préférée) : deux garanties pour que la bonne manette contrôle le bon joueur.
# Les lignes input_playerN_analog_dpad_mode (croix seule ou croix + un stick) sont recopiées telles quelles.
PLAYERS=/.config/agm-players
RACFG=/.config/retroarch/retroarch.cfg
[ -s "$PLAYERS" ] && [ -f "$RACFG" ] || exit 0

# Une ligne par manette : jsN <tab> chemin sysfs <tab> vvvv:pppp nom
LIST=$(awk '
    /^I:/ { v = ""; p = ""; for (i = 1; i <= NF; i++) { if ($i ~ /^Vendor=/) v = substr($i, 8); if ($i ~ /^Product=/) p = substr($i, 9) } }
    /^N: Name=/ { n = $0; sub(/^N: Name="/, "", n); sub(/"$/, "", n); gsub(/"/, "", n) }
    /^S: Sysfs=/ { s = substr($0, 10) }
    /^H: Handlers=/ { if (match($0, /js[0-9]+/)) print substr($0, RSTART + 2, RLENGTH - 2) "\t" s "\t" v ":" p " " n }
' /proc/bus/input/devices)
GM=$(printf '%s\n' "$LIST" | sed '/^$/d' | sort -n | cut -f2-)  # ordre Game Manager : sysfs <tab> manette
SDL=$(printf '%s\n' "$LIST" | sed '/^$/d' | cut -f2 | sort)      # ordre RetroArch : sysfs
COUNT=$(printf '%s\n' "$SDL" | sed '/^$/d' | wc -l)

OUT=$(free=$COUNT; grep -o '^input_player[1-4]_joypad_index = "[0-9]*"' "$PLAYERS" | while read -r line; do
    p=${line#input_player}; p=${p%%_*}
    i=${line##* = \"}; i=${i%\"}
    row=$(printf '%s\n' "$GM" | sed -n "$((i + 1))p")
    if [ -n "$row" ]; then
        sys=${row%%$'\t'*}; dev=${row#*$'\t'}
        idx=$(( $(printf '%s\n' "$SDL" | grep -nxF "$sys" | cut -d: -f1) - 1 )); type=1
    else  # manette absente : un numéro libre, sans réservation
        dev=""; idx=$free; free=$((free + 1)); type=0
    fi
    echo "input_player${p}_joypad_index = \"$idx\""
    echo "input_player${p}_reserved_device = \"$dev\""
    echo "input_player${p}_device_reservation_type = \"$type\""
done)

# Ce qui dirige chaque joueur (croix seule ou croix + un stick) : recopié tel quel, s'il a été choisi.
DPAD=$(grep -o '^input_player[1-4]_analog_dpad_mode = "[0-9]"' "$PLAYERS")
[ -n "$DPAD" ] && OUT=$(printf '%s\n%s' "$OUT" "$DPAD") && \
    sed -i -E '/^input_player[1-4]_analog_dpad_mode = /d' "$RACFG"

sed -i -E '/^input_player[1-4]_(joypad_index|reserved_device|device_reservation_type) = /d' "$RACFG"
printf '%s\n' "$OUT" >> "$RACFG"
cp "$PLAYERS" "$PLAYERS.applied"
echo "joueurs pour RetroArch : $(printf '%s\n' "$OUT" | grep -E 'joypad_index|reserved_device' | cut -d'"' -f2 | tr '\n' ' ')"
