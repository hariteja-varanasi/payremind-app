import re
from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# One Postgres database can hold several environments, one schema each.
SCHEMAS = ("dev", "test", "staging", "prod")
# Real customer data lives here: never seeded with demo data, never used by demo mode.
PROTECTED_SCHEMAS = frozenset({"prod", "public"})
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,30}$")


def validate_schema(schema: str) -> str:
    if not _SCHEMA_RE.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    return schema


def make_engine(url: str, schema: str = "") -> Engine:
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        if schema:
            raise ValueError("schemas need Postgres; SQLite has none")
        connect_args["check_same_thread"] = False
    elif ":6543/" in url:
        # Supabase/PgBouncer transaction pooling can't keep server-side prepared statements.
        connect_args["prepare_threshold"] = None
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if schema:
        # Validated name, so quoting it in SQL is safe.
        quoted = f'"{validate_schema(schema)}"'

        @event.listens_for(engine, "connect")
        def _set_search_path(dbapi_conn: Any, _record: Any) -> None:
            autocommit = dbapi_conn.autocommit
            dbapi_conn.autocommit = True
            with dbapi_conn.cursor() as cur:
                cur.execute(f"SET search_path TO {quoted}")
            dbapi_conn.autocommit = autocommit

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session
