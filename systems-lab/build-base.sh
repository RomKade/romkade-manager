#!/bin/sh
# Images de base du labo : système de fichiers des images officielles, allégé (pas de thèmes, de gros émulateurs ni
# de firmwares ; quelques cœurs RetroArch légers). Tout se passe dans Docker : rien n'est gardé sur le Mac.
set -e
V=agm-lab-src
docker volume create $V >/dev/null
case "$1" in
rocknix)
  docker run --rm -v $V:/src alpine:3.20 sh -c '
    apk add -q curl tar squashfs-tools >/dev/null
    U=https://github.com/ROCKNIX/distribution/releases/download/20261001/ROCKNIX-H700.aarch64-20261001.tar
    curl -sL $U | tar -xO --wildcards "*/SYSTEM" > /src/s && unsquashfs -q -n -d /src/root /src/s >/dev/null 2>&1; rm /src/s
    R=/src/root; cd $R/usr/lib/libretro && for f in *; do case "$f" in gambatte_*|snes9x_*|genesis_plus_gx_*|fceumm_*|mgba_*) ;; *) rm -rf "$f";; esac; done
    rm -rf $R/usr/lib/wine $R/usr/lib32 $R/usr/share/libretro-database $R/usr/share/*-shaders $R/usr/share/scummvm \
           $R/usr/share/themes $R/usr/share/soundfonts $R/usr/lib/vlc $R/usr/lib/librenderdoc.so
    cd $R/usr/bin && rm -f rclone syncthing duckstation-sa scummvm flycast box64 box86 ppsspp'
  TAG=agm-lab/rocknix-base:20261001 ;;
knulli)
  docker run --rm -v $V:/src alpine:3.20 sh -c '
    apk add -q curl tar gzip squashfs-tools >/dev/null
    U=https://github.com/knulli-cfw/distribution/releases/download/20250813/knulli-h700-rg-cubexx-gladiator-ii-20250813_boot.tar.gz
    curl -sL $U | tar -xzO boot/batocera.update > /src/s
    unsquashfs -q -n -d /src/root -excludes /src/s usr/lib/libretro usr/share/emulationstation/themes usr/share/sounds \
      usr/share/soundfonts usr/share/lr-mame usr/share/scummvm usr/bin/scummvm usr/share/hypseus-singe \
      usr/share/advanced_drastic lib/firmware usr/share/ppsspp usr/share/dosbox-x usr/bin/syncthing >/dev/null 2>&1
    unsquashfs -q -n -f -d /src/root /src/s usr/lib/libretro/gambatte_libretro.so usr/lib/libretro/snes9x_libretro.so \
      usr/lib/libretro/genesis_plus_gx_libretro.so usr/lib/libretro/mgba_libretro.so usr/lib/libretro/fceumm_libretro.so >/dev/null 2>&1
    rm /src/s'
  TAG=agm-lab/knulli-base:20250813 ;;
*) echo "usage : $0 rocknix|knulli"; exit 1 ;;
esac
docker run --rm -v $V:/src alpine:3.20 tar -C /src/root -c . | docker import --platform linux/arm64 - $TAG
docker run --rm -v $V:/src alpine:3.20 rm -rf /src/root
echo "$TAG prête"
