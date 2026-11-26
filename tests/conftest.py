import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from payremind.api.app import create_app
from payremind.config import Settings
from payremind.messaging.whatsapp import FakeSender
from payremind.migrate import upgrade
from payremind.models import Tenant
from payremind.security import hash_token

TODAY = date(2026, 12, 1)
CSV = (
    "Party Name,Mobile,Invoice No,Invoice Date,Due Date,Amount,Balance\n"
    'Sharma Traders,98450 12345,INV-1,01-10-2026,31-10-2026,"1,000.00",1000\n'
    "Gupta Stores,+91 9876543210,INV-2,01-11-2026,04-12-2026,500,500\n"
    "Rao & Sons,,INV-3,01-09-2026,01-09-2026,2500,2500\n"
)


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


# Set to a Postgres URL (CI does) to run the whole suite against Postgres instead of SQLite.
PG_URL = os.environ.get("PAYREMIND_TEST_DATABASE_URL")
APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
BASE_URL = "https://pay.example.in"


@pytest.fixture
def database_url(tmp_path):
    if PG_URL:
        engine = create_engine(PG_URL)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        engine.dispose()
        url = PG_URL
    else:
        url = f"sqlite:///{tmp_path}/t.db"
    upgrade(url)
    return url


@pytest.fixture
def app_and_tokens(database_url, sender):
    settings = Settings(
        database_url=database_url,
        whatsapp_app_secret=APP_SECRET,
        whatsapp_verify_token=VERIFY_TOKEN,
        public_base_url=BASE_URL,
    )
    app = create_app(settings, sender=sender, today=lambda: TODAY)
    factory = app.state.session_factory
    tokens = {"a": "token-a", "b": "token-b"}
    with factory() as s:
        s.add_all(
            [
                Tenant(
                    name="A",
                    upi_vpa="a@okaxis",
                    payee_name="A Co",
                    api_token_hash=hash_token(tokens["a"]),
                ),
                Tenant(
                    name="B",
                    upi_vpa="b@okhdfc",
                    payee_name="B Co",
                    api_token_hash=hash_token(tokens["b"]),
                ),
            ]
        )
        s.commit()
    return app, tokens


@pytest.fixture
def client(app_and_tokens):
    app, _ = app_and_tokens
    return TestClient(app)


@pytest.fixture
def auth(app_and_tokens):
    _, tokens = app_and_tokens
    return {k: {"Authorization": f"Bearer {v}"} for k, v in tokens.items()}


def upload(client, headers, content=CSV, name="o.csv"):
    return client.post("/imports", files={"file": (name, content.encode())}, headers=headers)
