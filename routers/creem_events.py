"""Signed production events augment the existing Creem checkout and approval flow."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from models import Business, CreemPayment
from models_platform import CreemWorkspaceSubscription
from services import creem
from services.creem_billing import date_field, now, object_id, record_paid_checkout
from services.marketplace import lock_calendar


router = APIRouter()
logger = logging.getLogger(__name__)
RENEWALS = {"subscription.paid", "subscription.canceled", "subscription.paused", "subscription.expired"}


def reconcile_access(business, subscription):
    blocked = (subscription.status == "paused"
               or bool(subscription.paid_until and subscription.paid_until <= now()))
    if blocked and business.is_active and business.payment_status == "approved":
        subscription.auto_blocked = True
        business.is_active, business.payment_status = False, "expired"
    elif not blocked and subscription.status == "active" and subscription.auto_blocked:
        if business.payment_status == "expired":
            business.is_active, business.payment_status = True, "approved"
        subscription.auto_blocked = False


async def completed(db, payload, created):
    local_id, checkout_id = payload.get("request_id"), payload.get("id")
    if not isinstance(local_id, str) or not isinstance(checkout_id, str):
        return
    payment = await db.get(CreemPayment, local_id)
    if not payment or payment.checkout_id != checkout_id:
        return
    await lock_calendar(db, payment.business_id)
    if not creem.is_paid(payload, checkout_id, payment.product_id, payment.cents):
        try:
            payload = await creem.api("GET", "checkouts", params={"checkout_id": checkout_id})
        except creem.CreemError as exc:
            raise HTTPException(503, "Awaiting provider verification.") from exc
        if not creem.is_paid(payload, checkout_id, payment.product_id, payment.cents):
            return
    business = await db.get(Business, payment.business_id)
    if business and business.billing_country == "creem":
        try:
            await record_paid_checkout(db, business, payment, payload, created)
        except creem.CreemError as exc:
            raise HTTPException(503, "Awaiting subscription verification.") from exc


async def renew(db, kind, payload, created):
    provider_id = payload.get("id")
    if not isinstance(provider_id, str):
        return
    business_id = await db.scalar(select(CreemWorkspaceSubscription.business_id).where(
        CreemWorkspaceSubscription.provider_id == provider_id))
    if business_id is None:
        return
    await lock_calendar(db, business_id)
    subscription = await db.get(CreemWorkspaceSubscription, business_id, populate_existing=True)
    if subscription.newest_event >= created or object_id(payload.get("product")) != subscription.product_id:
        return
    if kind == "subscription.paid":
        paid_until = date_field(payload, "current_period_end_date")
        if paid_until is None:
            raise HTTPException(422, "Missing billing period.")
        if subscription.paid_until is None or paid_until > subscription.paid_until:
            subscription.paid_until = paid_until
    subscription.status = "active" if kind == "subscription.paid" else kind.removeprefix("subscription.")
    subscription.newest_event = created
    if business := await db.get(Business, business_id):
        reconcile_access(business, subscription)


@router.post("/billing/creem/events")
async def creem_events(request: Request, db: AsyncSession = Depends(get_db)):
    secret = os.getenv("CREEM_WEBHOOK_SECRET", "").strip()
    if not creem.webhook_ready():
        raise HTTPException(503, "Creem events are not configured.")
    raw = await request.body()
    given = request.headers.get("creem-signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not re.fullmatch(r"[a-fA-F0-9]{64}", given) or not hmac.compare_digest(given.lower(), expected):
        raise HTTPException(401, "Invalid signature.")
    try:
        body = json.loads(raw)
        kind, payload, created = body["eventType"], body["object"], body["created_at"]
        if not isinstance(kind, str) or not isinstance(payload, dict) or type(created) is not int or not 0 < created < 10**14:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "Invalid event.")
    if payload.get("mode") == "test":
        raise HTTPException(422, "Production events only.")
    if kind == "checkout.completed":
        await completed(db, payload, created)
    elif kind in RENEWALS:
        await renew(db, kind, payload, created)
    await db.commit()
    return Response(status_code=204)


async def expire_subscriptions():
    while True:
        if creem.webhook_ready():
            try:
                async with AsyncSessionLocal() as db:
                    ids = (await db.scalars(select(CreemWorkspaceSubscription.business_id).join(
                        Business, Business.id == CreemWorkspaceSubscription.business_id
                    ).where(Business.is_active.is_(True), Business.payment_status == "approved",
                            or_(CreemWorkspaceSubscription.paid_until <= now(),
                                CreemWorkspaceSubscription.status == "paused")).limit(500))).all()
                    for business_id in ids:
                        await lock_calendar(db, business_id)
                        business = await db.get(Business, business_id)
                        subscription = await db.get(CreemWorkspaceSubscription, business_id)
                        if business and subscription:
                            reconcile_access(business, subscription)
                        await db.commit()
            except Exception:
                logger.exception("Unable to refresh expired billing periods")
        await asyncio.sleep(300)
