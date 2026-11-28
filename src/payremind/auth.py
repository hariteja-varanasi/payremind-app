"""Phone OTP sign-in and dashboard sessions.

Codes are 6 digits, valid 5 minutes, at most 5 guesses each, at most 3 codes per phone per
15 minutes. Only keyed hashes of codes and session tokens are stored. Requesting a code for an
unknown phone looks the same to the caller as for a known one.
"""

import contextlib
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from payremind.messaging.whatsapp import Sender, SendError
from payremind.models import OtpChallenge, Tenant, User, WebSession
from payremind.security import hash_token, new_token

OTP_TTL = 5 * 60
OTP_MAX_ATTEMPTS = 5
OTP_WINDOW = 15 * 60
OTP_MAX_PER_WINDOW = 3


def _code_hash(secret_key: str, phone: str, code: str) -> str:
    return hmac.new(secret_key.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def request_otp(session: Session, phone: str, now: int, sender: Sender, secret_key: str) -> None:
    user = session.scalar(select(User).where(User.phone_e164 == phone))
    if user is None:
        return
    recent = session.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone_e164 == phone, OtpChallenge.created_at > now - OTP_WINDOW)
    )
    if (recent or 0) >= OTP_MAX_PER_WINDOW:
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        OtpChallenge(
            phone_e164=phone,
            code_hash=_code_hash(secret_key, phone, code),
            created_at=now,
            expires_at=now + OTP_TTL,
        )
    )
    session.commit()
    # Same response either way; the user can ask again.
    with contextlib.suppress(SendError):
        sender.send_otp(phone, code)


@dataclass(frozen=True)
class NewSession:
    token: str
    csrf_token: str


def verify_otp(
    session: Session, phone: str, code: str, now: int, secret_key: str, session_days: int
) -> NewSession | None:
    challenge = session.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.phone_e164 == phone,
            OtpChallenge.consumed.is_(False),
            OtpChallenge.expires_at > now,
        )
        .order_by(OtpChallenge.id.desc())
        .limit(1)
    )
    if challenge is None or challenge.attempts >= OTP_MAX_ATTEMPTS:
        return None
    challenge.attempts += 1
    ok = hmac.compare_digest(challenge.code_hash, _code_hash(secret_key, phone, code.strip()))
    if not ok:
        session.commit()
        return None
    challenge.consumed = True
    user = session.scalar(select(User).where(User.phone_e164 == phone))
    if user is None:  # pragma: no cover  (codes are only issued to existing users)
        session.commit()
        return None
    return create_session(session, user, now, session_days)


def create_session(session: Session, user: User, now: int, session_days: int) -> NewSession:
    token, csrf = new_token(), new_token()
    session.add(
        WebSession(
            token_hash=hash_token(token),
            user_id=user.id,
            tenant_id=user.tenant_id,
            csrf_token=csrf,
            expires_at=now + session_days * 86400,
        )
    )
    session.commit()
    return NewSession(token, csrf)


def load_session(session: Session, token: str | None, now: int) -> tuple[WebSession, Tenant] | None:
    if not token or len(token) > 100:
        return None
    ws = session.scalar(select(WebSession).where(WebSession.token_hash == hash_token(token)))
    if ws is None or ws.expires_at <= now:
        return None
    tenant = session.get(Tenant, ws.tenant_id)
    if tenant is None:  # pragma: no cover
        return None
    return ws, tenant


def end_session(session: Session, ws: WebSession) -> None:
    session.delete(ws)
    session.commit()
