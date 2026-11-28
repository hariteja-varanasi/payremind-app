from alembic import context
from sqlalchemy import text

from payremind import models  # noqa: F401  (registers tables)
from payremind.db import Base, make_engine, validate_schema

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or ""
    schema = config.attributes.get("schema", "")
    connectable = make_engine(url, schema)  # rejects SQLite + schema and bad names
    if schema:
        # Create the schema before search_path points at it.
        admin = make_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{validate_schema(schema)}"'))
        admin.dispose()
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                version_table_schema=schema or None,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
