"""Apply a confirmed payment to its workspace while holding the business lock."""
import re
from datetime import datetime, timezone

from sqlalchemy import select

from models import CreemPayment
from models_platform import CreemTermsAcceptance, CreemWorkspaceSubscription
from services import creem


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def object_id(item):
    return item.get("id") if isinstance(item, dict) else item


def date_field(item, name):
    raw = item.get(name)
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else None


async def accepted_offer(db, business):
    acceptance = await db.get(CreemTermsAcceptance, business.id)
    return acceptance if acceptance and acceptance.plan_type == business.plan_type else None


async def record_paid_checkout(db, business, payment, checkout, created=0):
    """Persist provider evidence and activate self-service plans after acceptance."""
    acceptance = await accepted_offer(db, business)
    payment.paid = True
    if not payment.recurring:
        return

    remote = checkout.get("subscription")
    provider_id = object_id(remote)
    if not isinstance(provider_id, str) or not re.fullmatch(r"sub_[A-Za-z0-9]+", provider_id):
        if acceptance:
            raise creem.CreemError("Awaiting confirmation of the subscription ID")
        return

    subscription = await db.get(CreemWorkspaceSubscription, business.id, populate_existing=True)
    if not subscription:
        paid_until = date_field(remote, "current_period_end_date") if isinstance(remote, dict) else None
        if paid_until is None:
            remote = await creem.api("GET", f"subscriptions/{provider_id}")
            if remote.get("id") != provider_id or object_id(remote.get("product")) != payment.product_id:
                raise creem.CreemError("Subscription does not match the verified payment")
            paid_until = date_field(remote, "current_period_end_date")
        if paid_until is None:
            raise creem.CreemError("Awaiting confirmation of the subscription period")
        status = remote.get("status", "active")
        subscription = CreemWorkspaceSubscription(business_id=business.id, provider_id=provider_id,
            product_id=payment.product_id, paid_until=paid_until, newest_event=created, status=status)
        db.add(subscription)

    if (acceptance and business.payment_status == "pending" and subscription.provider_id == provider_id
            and subscription.product_id == payment.product_id and subscription.status == "active"
            and subscription.paid_until and subscription.paid_until > now()):
        payments = (await db.scalars(select(CreemPayment).where(CreemPayment.business_id == business.id))).all()
        actual = sorted((row.recurring, row.cents) for row in payments if row.paid)
        expected = sorted((row.recurring, row.cents) for row in creem.advertised(acceptance.plan_type))
        if payments and len(payments) == len(expected) and actual == expected:
            business.is_active = True
            business.payment_status = "approved"
