from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from nexusai.core.config import Settings

SCHEMA_REVISION = "0002_documents"


def create_database_engine(settings: Settings) -> Engine | None:
    if settings.database_url is None:
        return None
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=3,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
    )


def check_database(engine: Engine | None) -> str:
    if engine is None:
        return "not_configured"
    try:
        with engine.connect() as connection:
            revisions = connection.execute(text("SELECT version_num FROM app.alembic_version"))
            if list(revisions.scalars()) != [SCHEMA_REVISION]:
                return "migration_required"
        return "ready"
    except SQLAlchemyError:
        # Driver exceptions may contain credentials, hostnames or SQL. Do not return/log them.
        return "unavailable"
