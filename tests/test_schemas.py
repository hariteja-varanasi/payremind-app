import pytest
from sqlalchemy import create_engine, inspect, text

from payremind.billing.service import Supplier
from payremind.config import DEMO_SUPPLIER_GSTIN, Settings
from payremind.db import make_engine, make_sessionmaker, validate_schema
from payremind.demo import seed_demo
from payremind.migrate import upgrade
from payremind.models import Invoice, Tenant
from tests.conftest import PG_URL, TODAY

pg_only = pytest.mark.skipif(not PG_URL, reason="schemas need Postgres")
A, B = "pr_t_staging", "pr_t_prod"


@pytest.mark.parametrize("bad", ["", "Prod", "a-b", 'x"; drop', "1abc", "a" * 40])
def test_schema_names_are_validated(bad):
    with pytest.raises(ValueError):
        validate_schema(bad)


def test_sqlite_has_no_schemas(tmp_path):
    with pytest.raises(ValueError, match="SQLite"):
        make_engine(f"sqlite:///{tmp_path}/x.db", "dev")


def test_demo_refuses_prod_schema():
    with pytest.raises(ValueError, match="prod schema"):
        Settings(demo_mode=True, db_schema="prod")


@pytest.mark.parametrize("schema", ["prod", "public", ""])
def test_seed_refuses_protected_schemas_on_postgres(monkeypatch, capsys, schema):
    from payremind.cli import main
    from payremind.config import get_settings

    monkeypatch.setenv("PAYREMIND_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    monkeypatch.setenv("PAYREMIND_DB_SCHEMA", schema)
    if schema != "prod":
        monkeypatch.setenv("PAYREMIND_DEMO_MODE", "true")
    else:
        monkeypatch.setenv("PAYREMIND_DEMO_MODE", "false")
    get_settings.cache_clear()
    try:
        assert main(["seed-demo"]) == 2
        err = capsys.readouterr().err
        assert "PAYREMIND_DB_SCHEMA" in err or "only runs with PAYREMIND_DEMO_MODE" in err
    finally:
        get_settings.cache_clear()


def test_migrate_schemas_on_sqlite_is_an_error(tmp_path, monkeypatch, capsys):
    from payremind.cli import main
    from payremind.config import get_settings

    monkeypatch.setenv("PAYREMIND_DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    get_settings.cache_clear()
    try:
        assert main(["migrate", "--schemas", "dev"]) == 2
        assert main(["migrate", "--schemas", "bad-name"]) == 2
    finally:
        get_settings.cache_clear()


@pytest.fixture
def pg_schemas():
    def drop():
        e = create_engine(PG_URL)
        with e.begin() as conn:
            for s in (A, B):
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{s}" CASCADE'))
        e.dispose()

    drop()
    yield
    drop()


@pg_only
def test_each_schema_is_migrated_and_isolated(pg_schemas, monkeypatch, capsys):
    from payremind.cli import main
    from payremind.config import get_settings

    monkeypatch.setenv("PAYREMIND_DATABASE_URL", PG_URL)
    get_settings.cache_clear()
    try:
        assert main(["migrate", "--schemas", f"{A},{B}"]) == 0
        assert main(["migrate", "--schemas", f"{A},{B}"]) == 0  # idempotent
        assert f"schemas up to date: {A}, {B}" in capsys.readouterr().out
        # seed only the non-prod schema through the CLI, as the runbook does
        monkeypatch.setenv("PAYREMIND_DEMO_MODE", "true")
        monkeypatch.setenv("PAYREMIND_DB_SCHEMA", A)
        get_settings.cache_clear()
        assert main(["seed-demo"]) == 0
    finally:
        get_settings.cache_clear()

    plain = create_engine(PG_URL)
    insp = inspect(plain)
    for s in (A, B):
        assert {"invoices", "tenants", "alembic_version"} <= set(insp.get_table_names(schema=s))
    with plain.connect() as conn:
        rls = conn.execute(
            text(
                "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = :s and c.relkind = 'r' and not c.relrowsecurity"
            ),
            {"s": B},
        ).scalar()
    plain.dispose()
    assert rls == 0  # row-level security on every table in every schema

    for schema, invoices in ((A, 16), (B, 0)):
        engine = make_engine(PG_URL, schema)
        with make_sessionmaker(engine)() as s:
            assert s.query(Invoice).count() == invoices
        engine.dispose()

    # the seed lands in its own schema; a direct second seed keeps it at one demo business
    engine = make_engine(PG_URL, A)
    with make_sessionmaker(engine)() as s:
        seed_demo(s, TODAY, Supplier(DEMO_SUPPLIER_GSTIN, "29"))
        assert s.query(Tenant).count() == 1
    engine.dispose()


@pg_only
def test_app_reads_its_own_schema(pg_schemas):
    from fastapi.testclient import TestClient

    from payremind.api.app import create_app

    upgrade(PG_URL, schema=A)
    engine = make_engine(PG_URL, A)
    with make_sessionmaker(engine)() as s:
        seed_demo(s, TODAY, Supplier(DEMO_SUPPLIER_GSTIN, "29"))
    engine.dispose()
    c = TestClient(
        create_app(
            Settings(
                database_url=PG_URL,
                db_schema=A,
                demo_mode=True,
                secret_key="k",
                cookie_secure=False,
            )
        )
    )
    c.post("/login/demo")
    assert "Om Sai Provisions" in c.get("/app").text
