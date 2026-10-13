"""Opt-in tests against this project's dedicated PostgreSQL database, never SQLite."""

import os
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from nexusai.core.config import Settings
from nexusai.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def databases():
    if os.environ.get("NEXUS_RUN_DB_TESTS") != "1":
        pytest.skip("Set NEXUS_RUN_DB_TESTS=1 for dedicated PostgreSQL integration tests")
    load_dotenv()
    engines = {
        name: create_engine(os.environ[variable])
        for name, variable in (
            ("owner", "NEXUS_MIGRATION_DATABASE_URL"),
            ("writer", "NEXUS_DATABASE_URL"),
            ("reader", "NEXUS_ANALYTICS_DATABASE_URL"),
        )
    }
    for engine in engines.values():
        if engine.url.database != "nexusai":
            pytest.fail("Integration tests require the dedicated nexusai database")
    # Random internal identifiers, not user-provided SQL. Scoped fixture cleanup only.
    table = "permission_probe_" + uuid4().hex
    with engines["owner"].begin() as conn:
        conn.execute(text(f"CREATE TABLE analytics.{table} (id integer PRIMARY KEY)"))
        conn.execute(text(f"INSERT INTO analytics.{table} VALUES (1)"))
        conn.execute(text(f"GRANT SELECT ON analytics.{table} TO nexus_reader"))
        conn.execute(
            text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON analytics.{table} TO nexus_writer")
        )
    yield engines, table
    with engines["owner"].begin() as conn:
        conn.execute(text(f"DROP TABLE analytics.{table}"))
    for engine in engines.values():
        engine.dispose()


def test_readiness_against_real_postgres(databases):
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["database"] == "ready"


def test_writer_can_write_and_reader_can_read(databases):
    engines, table = databases
    with engines["writer"].begin() as conn:
        conn.execute(text(f"INSERT INTO analytics.{table} VALUES (2)"))
    with engines["reader"].connect() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM analytics.{table}")).scalar_one() >= 1
        assert conn.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO analytics.{table} VALUES (99)",
        "UPDATE analytics.{table} SET id = 99",
        "DELETE FROM analytics.{table}",
        "TRUNCATE analytics.{table}",
        "DROP TABLE analytics.{table}",
        "CREATE TABLE analytics.unauthorized (id integer)",
        "CREATE TABLE public.unauthorized (id integer)",
        "CREATE TEMP TABLE unauthorized (id integer)",
        "SELECT * FROM app.system_metadata",
        "SET ROLE nexus_writer",
        "SET ROLE nexus_owner",
        "SELECT pg_read_file('/etc/passwd')",
        "COPY analytics.{table} TO PROGRAM 'true'",
    ],
)
def test_reader_permissions_hold_even_with_readonly_disabled(databases, statement):
    engines, table = databases
    with engines["reader"].connect() as conn:
        # A user can change this default. ACLs must protect the database independently.
        conn.exec_driver_sql("SET default_transaction_read_only = off")
        conn.commit()
        try:
            with pytest.raises(DBAPIError) as caught:
                conn.execute(text(statement.format(table=table)))
            assert caught.value.orig.sqlstate == "42501"
        finally:
            conn.rollback()
            conn.exec_driver_sql("SET default_transaction_read_only = on")
            conn.commit()


def test_reader_has_no_automatic_access_to_new_tables(databases):
    engines, _ = databases
    name = "unapproved_" + uuid4().hex
    with engines["owner"].begin() as conn:
        conn.execute(text(f"CREATE TABLE analytics.{name} (id integer)"))
    try:
        with engines["reader"].connect() as conn:
            with pytest.raises(DBAPIError) as caught:
                conn.execute(text(f"SELECT * FROM analytics.{name}"))
            assert caught.value.orig.sqlstate == "42501"
    finally:
        with engines["owner"].begin() as conn:
            conn.execute(text(f"DROP TABLE analytics.{name}"))


def test_writer_cannot_modify_migration_history(databases):
    engines, _ = databases
    with engines["writer"].connect() as conn:
        with pytest.raises(DBAPIError) as caught:
            conn.execute(text("DELETE FROM app.alembic_version"))
        assert caught.value.orig.sqlstate == "42501"


def test_new_functions_are_not_publicly_executable(databases):
    engines, _ = databases
    name = "restricted_function_" + uuid4().hex
    with engines["owner"].begin() as conn:
        conn.execute(
            text(f"CREATE FUNCTION analytics.{name}() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
        )
    try:
        with engines["reader"].connect() as conn:
            with pytest.raises(DBAPIError) as caught:
                conn.execute(text(f"SELECT analytics.{name}()"))
            assert caught.value.orig.sqlstate == "42501"
    finally:
        with engines["owner"].begin() as conn:
            conn.execute(text(f"DROP FUNCTION analytics.{name}()"))
