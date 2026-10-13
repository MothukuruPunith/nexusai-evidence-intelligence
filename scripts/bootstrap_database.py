"""Provision roles in the dedicated local NexusAI database, before Alembic migrations."""

import os

from dotenv import load_dotenv
from psycopg import connect, sql
from sqlalchemy.engine import make_url


def main() -> None:
    load_dotenv()
    admin = make_url(os.environ["NEXUS_ADMIN_DATABASE_URL"])
    if admin.database != "nexusai":
        raise SystemExit("Bootstrap only supports the dedicated nexusai database")
    with connect(admin.set(drivername="postgresql").render_as_string(hide_password=False)) as conn:
        with conn.cursor() as cur:
            for env, expected in (
                ("NEXUS_MIGRATION_DATABASE_URL", "nexus_owner"),
                ("NEXUS_DATABASE_URL", "nexus_writer"),
                ("NEXUS_ANALYTICS_DATABASE_URL", "nexus_reader"),
            ):
                url = make_url(os.environ[env])
                if url.username != expected or not url.password:
                    raise SystemExit(f"Unexpected role or missing password for {env}")
                if (url.host, url.port, url.database) != (admin.host, admin.port, admin.database):
                    raise SystemExit("All provisioned roles must use the same dedicated database")
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (expected,))
                if cur.fetchone() is None:
                    cur.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                            sql.Identifier(expected), sql.Literal(url.password)
                        )
                    )
                else:
                    cur.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(expected), sql.Literal(url.password)
                        )
                    )
                cur.execute(
                    sql.SQL(
                        "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(expected))
                )
            cur.execute("REVOKE ALL ON DATABASE nexusai FROM PUBLIC")
            cur.execute(
                "GRANT CONNECT ON DATABASE nexusai TO nexus_owner,nexus_writer,nexus_reader"
            )
            cur.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            cur.execute("CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION nexus_owner")
            cur.execute("CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION nexus_owner")
            cur.execute("GRANT USAGE ON SCHEMA app TO nexus_writer")
            cur.execute("GRANT USAGE ON SCHEMA analytics TO nexus_writer,nexus_reader")
            cur.execute(
                "ALTER DEFAULT PRIVILEGES FOR ROLE nexus_owner IN SCHEMA app "
                "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO nexus_writer"
            )
            cur.execute(
                "ALTER DEFAULT PRIVILEGES FOR ROLE nexus_owner IN SCHEMA app "
                "GRANT USAGE,SELECT ON SEQUENCES TO nexus_writer"
            )
            # No automatic reader grants: each analytical relation must be explicitly approved.
            cur.execute(
                "ALTER DEFAULT PRIVILEGES FOR ROLE nexus_owner "
                "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
            )
            cur.execute("ALTER ROLE nexus_reader SET default_transaction_read_only = on")
            cur.execute("ALTER ROLE nexus_reader SET statement_timeout = '5s'")
            cur.execute("ALTER ROLE nexus_reader SET search_path = pg_catalog,analytics")
            cur.execute("ALTER ROLE nexus_writer SET search_path = pg_catalog,app")
    print("Dedicated database roles and schemas provisioned; credentials not displayed.")


if __name__ == "__main__":
    main()
