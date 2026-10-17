#!/bin/sh
# Premier démarrage de ROCKNIX, version conteneur : /storage préparé comme sur la console, puis sshd.
set -e
. /etc/profile.d/001-functions 2>/dev/null || true
if [ ! -f /storage/.lab-ready ]; then
  mkdir -p /storage/.config /storage/.cache/ssh /storage/roms/gb /storage/roms/snes /storage/roms/megadrive /storage/roms/savestates /storage/roms/bios \
           /storage/.config/retroarch/saves /storage/.config/retroarch/states /var/log
  cp -a /usr/config/. /storage/.config/ && cp -a /usr/cache/. /storage/.cache/
  # Pas d'écran, de son ni de manette dans un conteneur : RetroArch tourne « à vide » (le jeu tourne, invisible).
  sed -i -e 's/^video_driver = .*/video_driver = "null"/' -e 's/^audio_driver = .*/audio_driver = "null"/' \
         -e 's/^input_driver = .*/input_driver = "null"/' -e 's/^joypad_driver = .*/joypad_driver = "null"/' \
         /storage/.config/retroarch/retroarch.cfg
  python3 /lab/make_rom.py "/storage/roms/gb/Lab Test (World).gb"
  echo "LabTestSRAM" > "/storage/roms/gb/Lab Test (World).srm"
  touch /storage/.lab-ready
fi
mkdir -p /tmp/cores /run/sshd /var/empty && for f in /usr/lib/libretro/*; do ln -sf "$f" /tmp/cores/; done
setrootpass "${ROOT_PASSWORD:-rocknix}" >/dev/null 2>&1 || echo "root:${ROOT_PASSWORD:-rocknix}" | chpasswd
ssh-keygen -A >/dev/null 2>&1 || true
python3 /lab/fake_es.py /usr/config/emulationstation/es_systems.cfg &
exec /usr/sbin/sshd -D -e
