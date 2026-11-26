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
