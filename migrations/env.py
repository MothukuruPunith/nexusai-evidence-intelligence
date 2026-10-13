import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

load_dotenv()
url = os.environ.get("NEXUS_MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError("NEXUS_MIGRATION_DATABASE_URL is required")

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True, version_table_schema="app")
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, version_table_schema="app")
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
