import asyncio
from unittest.mock import AsyncMock, patch

from test_regressions import api
from fastapi import BackgroundTasks
from sqlalchemy import select
from starlette.requests import Request

from models import Business, CreemPayment, User
from routers.auth import creem_pay, pending_activation_page, register_post
from services.creem import Charge, is_paid


def test_free_registration_creates_a_restricted_workspace_without_payment_or_documents():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                request = Request({"type": "http", "session": {}, "client": ("free-registration", 1)})
                with patch("routers.auth.creem.charges", return_value=(
                    Charge("prod_setup", 13698, False), Charge("prod_monthly", 16742, True),
                )), patch("routers.auth.creem.api", new_callable=AsyncMock) as provider:
                    response = await register_post(
                        request, BackgroundTasks(), "New business", "+380671112233", "secure-password",
                        "clinic", None, "ua", "plan1", "yes", None, None, None, None,
                        None, None, None, db, registration_flow="access",
                    )
                    owner = await db.scalar(select(User).where(User.username == "+380671112233"))
                    assert owner is not None
                    assert response.headers["location"] == f"/pending-activation/{owner.business_id}"
                    company = await db.get(Business, owner.business_id)
                    assert company and not company.is_active and company.payment_status == "pending"
                    assert not any((company.receipt_url, company.nda_url, company.contract_url))
                    page = (await pending_activation_page(company.id, request, db)).body.decode()
                    assert "Обмежений доступ" in page and "Купити доступ · Creem" in page
                    assert "€136.98" in page and "€167.42" in page
                    provider.assert_not_awaited()

    asyncio.run(scenario())


def test_creem_verifies_the_exact_production_charge():
    checkout = {
        "mode": "prod", "id": "ch_setup", "request_id": "local", "status": "completed",
        "product": {"id": "prod_setup"},
        "order": {"status": "paid", "currency": "EUR", "sub_total": 13698,
                  "amount_due": 15000, "amount_paid": 15000},
    }
    assert is_paid(checkout, "ch_setup", "prod_setup", 13698)
    assert not is_paid({**checkout, "mode": "test"}, "ch_setup", "prod_setup", 13698)
    assert not is_paid(checkout, "ch_other", "prod_setup", 13698)
    assert not is_paid(checkout, "ch_setup", "prod_other", 13698)
    assert not is_paid(checkout, "ch_setup", "prod_setup", 16742)
    checkout["order"]["amount_paid"] = 13698
    assert not is_paid(checkout, "ch_setup", "prod_setup", 13698)


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
                    {"id": "ch_monthly", "checkout_url": "https://creem.io/checkout/ch_monthly"},
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
