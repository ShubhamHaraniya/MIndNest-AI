#!/bin/sh
# Creates the two limited database roles with the passwords from .env.production.
# Runs once, when the Postgres data volume is empty. Changing a password later does NOT re-run
# this: use `ALTER ROLE ... PASSWORD` (see docs/runbooks/production.md).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_pw="$APP_DB_PASSWORD" -v eval_pw="$EVAL_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE mindnest_app LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS', :'app_pw')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mindnest_app') \gexec
SELECT format('CREATE ROLE mindnest_eval LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS', :'eval_pw')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mindnest_eval') \gexec
SQL
