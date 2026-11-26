"""One-use, session-bound SMS challenges shared by both account types."""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from config import SECRET_KEY
from models_platform import PhoneChallenge
from services.marketplace import normalize_phone
from services.sms import send_sms
from utils.auth import AttemptLimiter


SESSION = "phone_challenges"
SIGNUP_CUSTOMER = "customer_signup"
SIGNIN_CUSTOMER = "customer_signin"
SIGNUP_BUSINESS = "business_signup"
SIGNIN_BUSINESS = "business_signin"
PER_ADDRESS = AttemptLimiter(limit=20, window=600)
PER_NUMBER = AttemptLimiter(limit=6, window=600)
COOLDOWN = timedelta(seconds=60)
LIFETIME = timedelta(minutes=8)


class ChallengeError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def provider():
    return SimpleNamespace(
        id="safeorbit-auth",
        sms_token=(os.getenv("AUTH_SMS_TOKEN") or os.getenv("MARKETPLACE_SMS_TOKEN") or "").strip(),
        sms_sender_id=(os.getenv("AUTH_SMS_SENDER") or os.getenv("MARKETPLACE_SMS_SENDER") or "").strip(),
    )


def enabled():
    return bool(provider().sms_token)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _digest(phone, purpose, nonce, code):
    return hmac.new(SECRET_KEY.encode(), f"sms:{purpose}:{phone}:{nonce}:{code}".encode(), hashlib.sha256).hexdigest()


def pending(request, purpose):
    return request.session.get(SESSION, {}).get(purpose)


def clear(request, *purposes):
    challenges = dict(request.session.get(SESSION, {}))
    for purpose in purposes:
        challenges.pop(purpose, None)
    if challenges:
        request.session[SESSION] = challenges
    else:
        request.session.pop(SESSION, None)


async def issue(request, db, purpose, raw_phone, *, identity=None, destination=""):
    phone = normalize_phone(raw_phone)
    if not phone:
        raise ChallengeError("Введіть номер у міжнародному форматі, наприклад +380 або +48.", 422)
    sender = provider()
    if not sender.sms_token:
        raise ChallengeError("SMS-підтвердження тимчасово недоступне. Спробуйте пізніше.", 503)
    address = request.client.host if request.client else "unknown"
    if not PER_ADDRESS.allow(address) or not PER_NUMBER.allow(phone):
        raise ChallengeError("Забагато запитів на SMS. Спробуйте пізніше.", 429)
    timestamp = now()
    nonce = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1000000):06d}"
    digest = _digest(phone, purpose, nonce, code)
    data = dict(nonce=nonce, digest=digest, sent_at=timestamp, expires_at=timestamp + LIFETIME, attempts=0, used=False)
    existing = await db.get(PhoneChallenge, (phone, purpose))
    if existing is None:
        db.add(PhoneChallenge(phone=phone, purpose=purpose, **data))
    else:
        result = await db.execute(update(PhoneChallenge).where(
            PhoneChallenge.phone == phone, PhoneChallenge.purpose == purpose,
            PhoneChallenge.sent_at <= timestamp - COOLDOWN,
        ).values(**data))
        if not result.rowcount:
            raise ChallengeError("Зачекайте хвилину перед повторним SMS.", 429)
    try:
        await db.execute(delete(PhoneChallenge).where(PhoneChallenge.sent_at < timestamp - timedelta(days=2)))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ChallengeError("Зачекайте хвилину перед повторним SMS.", 429) from exc
    async with httpx.AsyncClient() as http:
        ok, _ = await send_sms(http, sender, phone, f"SafeOrbit: {code}. Код дiйсний 8 хвилин. Не повiдомляйте його нiкому.")
    if not ok:
        await db.execute(update(PhoneChallenge).where(PhoneChallenge.nonce == nonce).values(used=True))
        await db.commit()
        raise ChallengeError("Не вдалося надіслати код. Спробуйте за хвилину.", 503)
    challenges = dict(request.session.get(SESSION, {}))
    challenges[purpose] = {"phone": phone, "nonce": nonce, "identity": identity, "destination": destination}
    request.session[SESSION] = challenges


async def consume(request, db, purpose, raw_code, *, expected_phone=None):
    challenge = pending(request, purpose)
    if not challenge or not re.fullmatch(r"[0-9]{6}", raw_code) or (
        expected_phone is not None and challenge["phone"] != normalize_phone(expected_phone)
    ):
        raise ChallengeError("Введіть шестизначний код для цього номера.", 422)
    phone, nonce = challenge["phone"], challenge["nonce"]
    current = (await db.execute(update(PhoneChallenge).where(
        PhoneChallenge.phone == phone, PhoneChallenge.purpose == purpose, PhoneChallenge.nonce == nonce,
        PhoneChallenge.expires_at > now(), PhoneChallenge.used.is_(False), PhoneChallenge.attempts < 5,
    ).values(attempts=PhoneChallenge.attempts + 1).returning(PhoneChallenge.digest))).scalar_one_or_none()
    if not current or not hmac.compare_digest(current, _digest(phone, purpose, nonce, raw_code)):
        await db.commit()
        raise ChallengeError("Код неправильний, сплив або вичерпано спроби.", 422)
    await db.execute(update(PhoneChallenge).where(PhoneChallenge.nonce == nonce).values(used=True))
    await db.commit()
    clear(request, purpose)
    return challenge
