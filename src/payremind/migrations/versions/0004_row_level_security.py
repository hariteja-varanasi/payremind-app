"""Enable row-level security on every table (Postgres only).

Supabase publishes the public schema through its REST API. With RLS on and no policies, that
API can read nothing, while the app, connecting as the tables' owner, is unaffected.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "tenants",
    "customers",
    "invoices",
    "promises",
    "reminder_log",
    "opt_outs",
    "users",
    "otp_challenges",
    "web_sessions",
    "billing_invoices",
    "processed_webhooks",
    "alembic_version",
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
