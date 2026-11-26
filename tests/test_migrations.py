from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from payremind.db import Base
from payremind.migrate import downgrade, upgrade


def test_migrations_match_models(database_url):
    engine = create_engine(database_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_and_upgrade_again(database_url):
    downgrade(database_url, "base")
    engine = create_engine(database_url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    upgrade(database_url)
    assert "invoices" in inspect(engine).get_table_names()
    engine.dispose()
