"""Admin CLI. Invite-only beta: tenants and their users are created here, not by sign-up."""

import argparse
import sys

from sqlalchemy.orm import Session, sessionmaker

from payremind.api.app import today_ist
from payremind.config import get_settings
from payremind.core.phone import normalize_indian_mobile
from payremind.core.upi import validate_vpa
from payremind.db import make_engine, make_sessionmaker
from payremind.messaging.whatsapp import FakeSender, make_sender
from payremind.migrate import upgrade
from payremind.models import Tenant, User
from payremind.security import hash_token, new_token
from payremind.services import run_all_tenants


def _sessions() -> sessionmaker[Session]:
    return make_sessionmaker(make_engine(get_settings().database_url))


def invite(name: str, upi_vpa: str, payee_name: str, owner_phone: str) -> tuple[int, str]:
    validate_vpa(upi_vpa)
    phone = normalize_indian_mobile(owner_phone)
    if phone is None:
        raise ValueError(f"invalid Indian mobile number: {owner_phone!r}")
    token = new_token()
    with _sessions()() as session:
        tenant = Tenant(
            name=name, upi_vpa=upi_vpa, payee_name=payee_name, api_token_hash=hash_token(token)
        )
        session.add(tenant)
        session.flush()
        session.add(User(tenant_id=tenant.id, phone_e164=phone))
        session.commit()
        return tenant.id, token


def add_user(tenant_id: int, phone_raw: str) -> None:
    phone = normalize_indian_mobile(phone_raw)
    if phone is None:
        raise ValueError(f"invalid Indian mobile number: {phone_raw!r}")
    with _sessions()() as session:
        if session.get(Tenant, tenant_id) is None:
            raise ValueError(f"no tenant {tenant_id}")
        session.add(User(tenant_id=tenant_id, phone_e164=phone))
        session.commit()


def run_reminders_daily() -> str:
    settings = get_settings()
    sender = make_sender(
        settings.whatsapp_token, settings.whatsapp_phone_number_id, settings.whatsapp_api_base
    )
    note = " (dry run: WhatsApp not configured)" if isinstance(sender, FakeSender) else ""
    with _sessions()() as session:
        r = run_all_tenants(session, today_ist(), sender, settings.public_base_url)
    return f"{r.tenants} businesses, {r.sent} sent, {r.failed} failed{note}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="payremind")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("invite", help="create a beta business; prints its API token once")
    inv.add_argument("--name", required=True)
    inv.add_argument("--upi", required=True)
    inv.add_argument("--payee", required=True)
    inv.add_argument("--owner-phone", required=True, help="WhatsApp number used to sign in")
    au = sub.add_parser("add-user", help="let another phone sign in to a business")
    au.add_argument("--tenant", type=int, required=True)
    au.add_argument("--phone", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("run-reminders", help="daily job: send due reminders for every business")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "migrate":
            upgrade(get_settings().database_url)
            print("database is up to date")
        elif args.cmd == "invite":
            tenant_id, token = invite(args.name, args.upi, args.payee, args.owner_phone)
            print(f"tenant {tenant_id} created. API token (shown once): {token}")
        elif args.cmd == "add-user":
            add_user(args.tenant, args.phone)
            print("user added")
        else:
            print(run_reminders_daily())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
