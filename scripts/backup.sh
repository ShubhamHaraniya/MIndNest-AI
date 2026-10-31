#!/usr/bin/env bash
# Makes one backup: the database, every uploaded file, and a checksum list.
#
#   scripts/backup.sh
#
# Writes $BACKUP_DIR/<date-time>/{db.dump,files.tar,SHA256SUMS}. With BACKUP_PASSPHRASE set, the
# two data files are encrypted (db.dump.enc, files.tar.enc). Old backups are removed after
# BACKUP_KEEP_DAYS days. Schedule it with cron; see docs/runbooks/backup-restore.md.
#
# NOT included: .env.production. Keep SECRET_KEY and the other secrets in a password manager.
# Without SECRET_KEY, the AI provider keys inside a restored database cannot be read.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${MINDNEST_ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }

get() {
  { grep -E "^$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2- | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//'
}
prod() { scripts/prod.sh "$@"; }

BACKUP_DIR="$(get BACKUP_DIR)"; BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="$(get BACKUP_KEEP_DAYS)"; KEEP_DAYS="${KEEP_DAYS:-14}"
PASSPHRASE="$(get BACKUP_PASSPHRASE)"

case "$KEEP_DAYS" in ''|*[!0-9]*) echo "BACKUP_KEEP_DAYS must be a whole number" >&2; exit 1 ;; esac

umask 077
stamp="$(date -u +%Y%m%d-%H%M%S)"
final="$BACKUP_DIR/$stamp"
work="$BACKUP_DIR/.partial-$stamp"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

echo "1/4 Dumping the database ..."
prod exec -T postgres pg_dump -U mindnest -d mindnest -Fc > "$work/db.dump"
prod exec -T postgres pg_restore --list < "$work/db.dump" > /dev/null   # readable?

echo "2/4 Copying uploaded files ..."
prod run --rm --no-deps -T api python -m mindnest_core.storagesync export > "$work/files.tar"
tar -tf "$work/files.tar" > /dev/null                                  # readable?

if [ -n "$PASSPHRASE" ]; then
  echo "3/4 Encrypting ..."
  for name in db.dump files.tar; do
    BACKUP_PASSPHRASE="$PASSPHRASE" openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
      -pass env:BACKUP_PASSPHRASE -in "$work/$name" -out "$work/$name.enc"
    rm -f "$work/$name"
  done
else
  echo "3/4 BACKUP_PASSPHRASE is empty: backup files are NOT encrypted. Keep them somewhere private."
fi

echo "4/4 Writing checksums and removing old backups ..."
( cd "$work" && sha256sum db.dump* files.tar* > SHA256SUMS )
mv "$work" "$final"
trap - EXIT
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime "+$KEEP_DAYS" -exec rm -rf {} +

echo "Done: $final"
du -sh "$final" | cut -f1 | sed 's/^/Size: /'
echo "Copy this folder to another machine or an outside storage service as well."
