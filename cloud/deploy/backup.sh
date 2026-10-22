#!/bin/sh
# Sauvegarde quotidienne de la base ROMKADE Cloud (cloud.sqlite3) vers l'hébergement OVH, par SFTP.
#
# Lancé par la crontab du compte de déploiement de la droplet :
#   30 3 * * * $HOME/app/romkade-cloud/cloud/deploy/backup.sh >> $HOME/app/romkade-cloud/backup.log 2>&1
#
# - copie cohérente faite par SQLite lui-même (API backup), même pendant que le serveur écrit, puis vérifiée ;
# - envoyée hors de www (jamais servie sur le web), lisible par le seul compte OVH ;
# - rotation sans suppression : cloud-jour-01..31 (un mois glissant) écrasés chaque mois, et cloud-mois-AAAA-MM
#   gardé pour toujours (le premier du mois). Fonctionne avec un accès SFTP seul (offres OVH sans SSH).
#
# Configuration (~/app/romkade-cloud/backup.env, hors dépôt) :
#   OVH_BACKUP_TARGET=identifiant@ssh.clusterXXX.hosting.ovh.net
#   OVH_BACKUP_DIR=backups/romkade-cloud        (facultatif)
# Clé SSH dédiée : ~/.ssh/romkade_backup (sans phrase de passe), autorisée sur OVH avec ssh-copy-id -s.
set -eu

CONF="$HOME/app/romkade-cloud/backup.env"
[ -f "$CONF" ] && . "$CONF"
: "${OVH_BACKUP_TARGET:?OVH_BACKUP_TARGET manquant dans $CONF}"
DIR="${OVH_BACKUP_DIR:-backups/romkade-cloud}"
KEY="$HOME/.ssh/romkade_backup"
CONTAINER=romkade-cloud

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"; docker exec "$CONTAINER" rm -f /tmp/backup.sqlite3 >/dev/null 2>&1 || true' EXIT

echo "$(date -Iseconds) début"
docker exec "$CONTAINER" python -c "
import sqlite3, sys
src = sqlite3.connect('/data/cloud.sqlite3'); dst = sqlite3.connect('/tmp/backup.sqlite3')
src.backup(dst)
ok = dst.execute('PRAGMA integrity_check').fetchone()[0]
n = dst.execute('SELECT COUNT(*) FROM consoles').fetchone()[0]
dst.close(); src.close()
print(f'intégrité {ok}, {n} consoles'); sys.exit(ok != 'ok')
"
docker exec "$CONTAINER" cat /tmp/backup.sqlite3 | gzip -9 > "$TMP/backup.sqlite3.gz"
gzip -t "$TMP/backup.sqlite3.gz"

DAY="cloud-jour-$(date +%d).sqlite3.gz"
{
  echo "-mkdir $(dirname "$DIR")"
  echo "-mkdir $DIR"
  echo "put $TMP/backup.sqlite3.gz $DIR/$DAY"
  echo "chmod 600 $DIR/$DAY"
  if [ "$(date +%d)" = "01" ]; then
    MONTH="cloud-mois-$(date +%Y-%m).sqlite3.gz"
    echo "put $TMP/backup.sqlite3.gz $DIR/$MONTH"
    echo "chmod 600 $DIR/$MONTH"
  fi
} > "$TMP/batch"
sftp -q -b "$TMP/batch" -i "$KEY" -o BatchMode=yes -o IdentitiesOnly=yes "$OVH_BACKUP_TARGET" >/dev/null
echo "$(date -Iseconds) envoyé : $DIR/$DAY ($(wc -c < "$TMP/backup.sqlite3.gz") octets)"
