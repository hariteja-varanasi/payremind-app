from payremind.config import Settings


def test_placeholders_become_empty(monkeypatch):
    monkeypatch.setenv("PAYREMIND_WHATSAPP_TOKEN", "unset")
    monkeypatch.setenv("PAYREMIND_RAZORPAY_KEY_ID", "rzp_live_x")
    s = Settings()
    assert s.whatsapp_token == "" and s.razorpay_key_id == "rzp_live_x"


def test_database_url_built_from_parts():
    s = Settings(db_host="db.internal", db_password="p@ss/w:rd")
    assert s.database_url == (
        "postgresql+psycopg://payremind:p%40ss%2Fw%3Ard@db.internal:5432/payremind?sslmode=require"
    )


def test_database_url_untouched_without_host():
    assert Settings(database_url="sqlite:///x.db").database_url == "sqlite:///x.db"


def test_supabase_style_urls_are_normalised():
    s = Settings(
        database_url="postgresql://postgres.abc:pw@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
    )
    assert s.database_url == (
        "postgresql+psycopg://postgres.abc:pw@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
        "?sslmode=require"
    )
    assert Settings(database_url="postgres://u:p@h/db?sslmode=verify-full").database_url == (
        "postgresql+psycopg://u:p@h/db?sslmode=verify-full"
    )
    assert Settings(database_url="postgresql://u:p@h/db?x=1").database_url.endswith(
        "?x=1&sslmode=require"
    )
    local = "postgresql+psycopg://payremind:payremind@db:5432/payremind"
    assert Settings(database_url=local).database_url == local


def test_transaction_pooler_disables_prepared_statements():
    from payremind.db import make_engine

    e = make_engine("postgresql+psycopg://u:p@h:6543/db?sslmode=require")
    assert e.dialect.name == "postgresql"
    e.dispose()
