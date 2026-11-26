"""Admin CLI. Invite-only beta: tenants are created here, not by public sign-up."""

import argparse

from payremind.config import get_settings
from payremind.core.upi import validate_vpa
from payremind.db import make_engine, make_sessionmaker
from payremind.migrate import upgrade
from payremind.models import Tenant
from payremind.security import hash_token, new_token


def invite(name: str, upi_vpa: str, payee_name: str) -> tuple[int, str]:
    validate_vpa(upi_vpa)
    engine = make_engine(get_settings().database_url)
    token = new_token()
    with make_sessionmaker(engine)() as session:
        tenant = Tenant(
            name=name, upi_vpa=upi_vpa, payee_name=payee_name, api_token_hash=hash_token(token)
        )
        session.add(tenant)
        session.commit()
        return tenant.id, token


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="payremind")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("invite", help="create a beta tenant and print its API token once")
    inv.add_argument("--name", required=True)
    inv.add_argument("--upi", required=True)
    inv.add_argument("--payee", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    args = parser.parse_args(argv)
    if args.cmd == "migrate":
        upgrade(get_settings().database_url)
        print("database is up to date")
        return
    tenant_id, token = invite(args.name, args.upi, args.payee)
    print(f"tenant {tenant_id} created. token (shown once): {token}")


if __name__ == "__main__":  # pragma: no cover
    main()
