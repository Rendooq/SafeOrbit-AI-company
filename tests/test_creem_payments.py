import asyncio
from unittest.mock import AsyncMock, patch

from test_regressions import api
from starlette.requests import Request

from models import Business, CreemPayment
from routers.auth import creem_pay
from services.creem import Charge, is_paid


def test_creem_verifies_the_exact_production_charge():
    checkout = {
        "mode": "prod", "id": "ch_setup", "request_id": "local", "status": "completed",
        "product": {"id": "prod_setup"},
        "order": {"status": "paid", "currency": "EUR", "sub_total": 13698,
                  "amount_due": 15000, "amount_paid": 15000},
    }
    assert is_paid(checkout, "ch_setup", "local", "prod_setup", 13698)
    assert not is_paid({**checkout, "mode": "test"}, "ch_setup", "local", "prod_setup", 13698)
    assert not is_paid(checkout, "ch_setup", "other", "prod_setup", 13698)
    assert not is_paid(checkout, "ch_setup", "local", "prod_other", 13698)
    assert not is_paid(checkout, "ch_setup", "local", "prod_setup", 16742)
    checkout["order"]["amount_paid"] = 13698
    assert not is_paid(checkout, "ch_setup", "local", "prod_setup", 13698)


def test_creem_checkout_belongs_to_the_registration_and_confirms_first_charge():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                company = await db.get(Business, 1)
                company.billing_country = "creem"
                company.payment_status = "pending"
                company.is_active = False
                db.add_all([
                    CreemPayment(id="setup", business_id=1, product_id="prod_setup", cents=13698,
                                 recurring=False, checkout_id="ch_setup"),
                    CreemPayment(id="monthly", business_id=1, product_id="prod_monthly", cents=16742, recurring=True),
                ])
                await db.commit()

                provider = AsyncMock(side_effect=[
                    {"mode": "prod", "id": "ch_setup", "request_id": "setup", "status": "completed",
                     "product": {"id": "prod_setup"},
                     "order": {"status": "paid", "currency": "EUR", "sub_total": 13698,
                               "amount_due": 13698, "amount_paid": 13698}},
                    {"id": "prod_monthly", "currency": "EUR", "price": 16742, "status": "active",
                     "billing_type": "recurring", "billing_period": "every-month"},
                    {"id": "ch_monthly", "request_id": "monthly", "checkout_url": "https://creem.io/checkout/ch_monthly"},
                ])
                request = Request({"type": "http", "session": {"pending_business_id": 2}})
                with patch("routers.auth.creem.api", provider), patch(
                    "routers.auth.creem.charges",
                    return_value=(Charge("prod_setup", 13698, False), Charge("prod_monthly", 16742, True)),
                ):
                    denied = await creem_pay(1, request, db)
                    assert denied.headers["location"] == "/login"
                    provider.assert_not_awaited()
                    request.session["pending_business_id"] = 1
                    redirect = await creem_pay(1, request, db)

                assert redirect.headers["location"] == "https://creem.io/checkout/ch_monthly"
                assert (await db.get(CreemPayment, "setup")).paid
                assert not (await db.get(CreemPayment, "monthly")).paid
                assert not company.is_active

    asyncio.run(scenario())
