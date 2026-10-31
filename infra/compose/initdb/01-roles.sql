-- Development roles, created once when the Postgres container first starts.
-- mindnest_app serves the API and workers and is subject to row-level security.
-- mindnest_eval can only reach the eval schema, so evaluation code never sees student data.
-- In production, create these roles with strong passwords kept outside version control.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mindnest_app') THEN
    CREATE ROLE mindnest_app LOGIN PASSWORD 'mindnest_app' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mindnest_eval') THEN
    CREATE ROLE mindnest_eval LOGIN PASSWORD 'mindnest_eval' NOSUPERUSER NOBYPASSRLS;
  END IF;
END
$$;
