#!/usr/bin/env bash
# Runs docker compose for the production stack with your settings file.
#
#   scripts/prod.sh up -d --build     check settings, build, start everything
#   scripts/prod.sh ps                what is running
#   scripts/prod.sh logs -f api       follow one service's log
#   scripts/prod.sh check             only check .env.production
#
# Set MINDNEST_ENV_FILE to use a settings file other than .env.production.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${MINDNEST_ENV_FILE:-.env.production}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy .env.production.example to $ENV_FILE and fill it in." >&2
  exit 1
fi

check_settings() {
  if command -v python3 >/dev/null 2>&1; then
    python3 libs/core/mindnest_core/prodcheck.py "$ENV_FILE"
  else
    echo "python3 not found: skipping the settings check (install Python 3 to enable it)." >&2
  fi
}

case "${1:-}" in
  check) check_settings; exit $? ;;
  up) check_settings ;;
esac

# Profiles (storage, models) are listed in the settings file.
profiles="$(grep -E '^COMPOSE_PROFILES=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d ' ' || true)"
export COMPOSE_PROFILES="$profiles"

exec docker compose --env-file "$ENV_FILE" -f compose.prod.yaml "$@"
