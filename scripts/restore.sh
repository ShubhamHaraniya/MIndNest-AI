#!/usr/bin/env bash
# Restores a backup made by scripts/backup.sh. This REPLACES the current database and adds the
# backed-up files to storage.
#
#   scripts/restore.sh /srv/mindnest-backups/20261027-020000        asks before doing anything
#   scripts/restore.sh <folder> --yes                                no question (for tests/scripts)
#
# The settings file must be the one the backup was made with (above all SECRET_KEY).
set -euo pipefail
cd "$(dirname "$0")/.."

folder="${1:-}"
[ -n "$folder" ] && [ -d "$folder" ] || { echo "usage: scripts/restore.sh <backup-folder> [--yes]" >&2; exit 2; }
folder="$(cd "$folder" && pwd)"
assume_yes="${2:-}"

ENV_FILE="${MINDNEST_ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }
get() {
  { grep -E "^$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2- | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//'
}
prod() { scripts/prod.sh "$@"; }

[ -f "$folder/SHA256SUMS" ] || { echo "$folder has no SHA256SUMS; is it a backup folder?" >&2; exit 1; }
echo "Checking the backup files ..."
( cd "$folder" && sha256sum -c SHA256SUMS )

umask 077
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [ -f "$folder/db.dump.enc" ]; then
  PASSPHRASE="$(get BACKUP_PASSPHRASE)"
  [ -n "$PASSPHRASE" ] || { echo "This backup is encrypted but BACKUP_PASSPHRASE is empty in $ENV_FILE" >&2; exit 1; }
  for name in db.dump files.tar; do
    BACKUP_PASSPHRASE="$PASSPHRASE" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
      -pass env:BACKUP_PASSPHRASE -in "$folder/$name.enc" -out "$tmp/$name"
  done
  dump="$tmp/db.dump"; files="$tmp/files.tar"
else
  dump="$folder/db.dump"; files="$folder/files.tar"
fi

if [ "$assume_yes" != "--yes" ]; then
  echo
  echo "This will DELETE the current MindNest database and replace it with the one in:"
  echo "  $folder"
  read -r -p "Type RESTORE to continue: " answer
  [ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }
fi

echo "1/5 Stopping the website and workers ..."
prod stop caddy web api worker eval-worker || true

echo "2/5 Starting the database ..."
prod up -d --wait postgres redis
case ",$(get COMPOSE_PROFILES)," in *,storage,*) prod up -d storage ;; esac

echo "3/5 Replacing the database ..."
prod exec -T postgres psql -U mindnest -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS mindnest WITH (FORCE)" \
  -c "CREATE DATABASE mindnest OWNER mindnest"
prod exec -T postgres pg_restore -U mindnest -d mindnest --no-owner --exit-on-error < "$dump"

echo "4/5 Putting the files back ..."
prod run --rm --no-deps -T api python -m mindnest_core.storagesync import < "$files"

echo "5/5 Starting everything (this also applies any newer migrations) ..."
prod up -d

echo "Restored from $folder."
echo "Check https://$(get DOMAIN)/api/v1/ready and sign in to confirm."
