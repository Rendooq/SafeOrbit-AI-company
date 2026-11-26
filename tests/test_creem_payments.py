import asyncio
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from test_regressions import api
from fastapi import BackgroundTasks
import pytest
from sqlalchemy import select
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request

from models import ActivationDocument, Business, CreemPayment, User
from models_platform import CreemTermsAcceptance, CreemWorkspaceSubscription
from routers.auth import creem_pay, pending_activation_page, register_post, submit_access_documents
from services.creem import Charge, charges, is_paid
from utils.static import CachedStaticFiles


def test_activation_documents_are_atomic_and_private():
    async def scenario():
        pdf = b"%PDF-1.4\nactivation"
        upload = lambda data: UploadFile(io.BytesIO(data), filename="document.pdf")
        async with api() as (_, sessions):
            async with sessions() as db:
                business = await db.get(Business, 1)
                business.billing_country = "creem"
                business.payment_status = "pending"
                await db.commit()
                request = Request({"type": "http", "session": {"pending_business_id": 1}})
                invalid = await submit_access_documents(1, request, upload(pdf), upload(b"invalid"), db)
                assert invalid.headers["location"].endswith("payment_error=documents")
                assert not (await db.scalars(select(ActivationDocument))).all()
                await submit_access_documents(1, request, upload(pdf), upload(pdf), db)
                assert (await db.get(ActivationDocument, business.nda_url)).content == pdf
                path = business.nda_url.removeprefix("/static/")

            static = CachedStaticFiles(directory="static")
            scope = {"type": "http", "method": "GET", "session": {"pending_business_id": 2}}
            with patch("utils.static.AsyncSessionLocal", sessions):
                with pytest.raises(HTTPException) as forbidden:
                    await static.get_response(path, scope)
                assert forbidden.value.status_code == 404
                scope["session"]["pending_business_id"] = 1
                response = await static.get_response(path, scope)
                assert response.body == pdf
                assert response.headers["cache-control"] == "private, no-store"

    asyncio.run(scenario())


def test_free_registration_creates_a_restricted_workspace_without_payment_or_documents():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                request = Request({"type": "http", "session": {}, "headers": [], "client": ("free-registration", 1)})
                with patch("routers.auth.creem.charges", return_value=(
                    Charge("prod_newmonthly", 990, True),
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
                    assert "€9.90" in page and "Разове налаштування" not in page
                    assert "/static/contract_business_monthly.pdf" in page
                    payments = (await db.scalars(select(CreemPayment).where(CreemPayment.business_id == company.id))).all()
                    assert [(row.product_id, row.cents, row.recurring) for row in payments] == [("prod_newmonthly", 990, True)]
                    provider.assert_not_awaited()
                    provider.side_effect = [
                        {"id": "prod_newmonthly", "currency": "EUR", "price": 990, "status": "active",
                         "billing_type": "recurring", "billing_period": "every-month"},
                        {"id": "ch_businessmonthly", "checkout_url": "https://checkout.creem.io/ch_businessmonthly"},
                    ]
                    checkout = await creem_pay(company.id, request, db)
                    assert checkout.headers["location"] == "https://checkout.creem.io/ch_businessmonthly"
                    assert provider.await_count == 2
                    assert provider.await_args.kwargs["json"]["product_id"] == "prod_newmonthly"

    asyncio.run(scenario())


def test_business_creem_configuration_needs_only_the_new_monthly_product():
    with patch.dict("os.environ", {
        "CREEM_API_KEY": "creem_local_unit_test",
        "CREEM_ENABLED": "1",
        "CREEM_BUSINESS_MONTHLY_V2_PRODUCT_ID": "prod_newmonthly",
    }, clear=True):
        assert charges("plan1") == (Charge("prod_newmonthly", 990, True),)
        assert charges("plan2") == ()


@pytest.mark.parametrize("confirmation", ["webhook", "return"])
def test_online_plan_requires_approved_offer_and_activates_only_after_confirmed_payment(confirmation):
    from test_platform import post, test_app

    key = "isolated-signing-secret"
    configuration = {
        "CREEM_API_KEY": "creem_local_unit_test",
        "CREEM_ENABLED": "1",
        "CREEM_WEBHOOK_SECRET": key,
        "CREEM_CUSTOM_MONTHLY_PRODUCT_ID": "prod_constructor",
        "CREEM_ONLINE_TERMS_VERSION": "",
        "AUTH_SMS_TOKEN": "",
        "MARKETPLACE_SMS_TOKEN": "",
    }

    async def scenario():
        async with test_app() as (owner, webhook, sessions):
            assert (await owner.get("/terms/subscription/custom")).status_code == 404
            assert charges("custom") == ()
            with patch.dict("os.environ", {"CREEM_ONLINE_TERMS_VERSION": "2026-11-26"}):
                terms = await owner.get("/terms/subscription/custom")
                assert terms.status_code == 200 and "€19.80" in terms.text
                await owner.get("/register")
                submitted = await post(owner, "/register", {"name": "Constructor", "phone": "+380677701531",
                    "password": "valid constructor password", "type": "other", "terms_accepted": "yes",
                    "registration_flow": "access"})
                pending = submitted.headers["location"]
                page = await owner.get(pending)
                assert 'name="accept_offer"' in page.text and "/documents" not in page.text
                refused = await post(owner, pending + "/pay", {})
                assert refused.headers["location"].endswith("payment_error=terms")
                async with sessions() as db:
                    company = await db.scalar(select(Business))
                    assert not company.is_active and not await db.get(CreemTermsAcceptance, company.id)
                    business_id = company.id
                    payment_id = await db.scalar(select(CreemPayment.id))
                product = {"id": "prod_constructor", "currency": "EUR", "price": 1980,
                           "status": "active", "billing_type": "recurring", "billing_period": "every-month"}
                with patch("services.creem.api", AsyncMock(side_effect=[product,
                        {"id": "ch_constructor", "checkout_url": "https://checkout.creem.io/ch_constructor"}])):
                    created = await post(owner, pending + "/pay", {"accept_offer": "2026-11-26"})
                    assert created.headers["location"] == "https://checkout.creem.io/ch_constructor"
                async with sessions() as db:
                    assert not (await db.get(Business, business_id)).is_active
                    assert (await db.get(CreemTermsAcceptance, business_id)).version == "2026-11-26"
                date = datetime.now(timezone.utc)
                payment = {"id": "ch_constructor", "request_id": payment_id, "mode": "prod", "status": "completed",
                    "product": "prod_constructor", "order": {"status": "paid", "currency": "EUR",
                        "sub_total": 1980, "amount_due": 1980, "amount_paid": 1980},
                    "subscription": {"id": "sub_constructor", "status": "active",
                        "current_period_end_date": (date + timedelta(days=30)).isoformat()}}
                if confirmation == "webhook":
                    raw = json.dumps({"eventType": "checkout.completed", "object": payment,
                                      "created_at": int(date.timestamp() * 1000)}).encode()
                    signature = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
                    assert (await webhook.post("/billing/creem/events", content=raw,
                                              headers={"creem-signature": signature})).status_code == 204
                else:
                    with patch("services.creem.api", AsyncMock(return_value=payment)):
                        assert (await post(owner, pending + "/pay", {"verify_only": "true"})).status_code == 303
                async with sessions() as db:
                    company = await db.get(Business, business_id)
                    assert company.is_active and company.payment_status == "approved"
                    assert (await db.get(CreemWorkspaceSubscription, business_id)).provider_id == "sub_constructor"

    with patch.dict("os.environ", configuration):
        asyncio.run(scenario())


def test_single_paid_business_subscription_can_be_approved_with_documents():
    from routers.superadmin import approve_payment

    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                company = await db.get(Business, 1)
                company.billing_country = "creem"
                company.payment_status = "pending"
                company.is_active = False
                operator = User(id=200, username="price-approver", password="unused", role="superadmin")
                payment = CreemPayment(id="business-monthly", business_id=1, product_id="prod_newmonthly",
                                       cents=990, recurring=True, paid=True)
                db.add_all([operator, payment])
                await db.commit()
                with pytest.raises(HTTPException, match="підписані документи"):
                    await approve_payment(1, operator, db)
                company.nda_url = "/static/uploads/documents/signed-nda.pdf"
                company.contract_url = "/static/uploads/documents/signed-contract.pdf"
                company.plan_type = "plan2"
                await db.commit()
                with pytest.raises(HTTPException, match="підтвердження оплати"):
                    await approve_payment(1, operator, db)
                company.plan_type = "plan1"
                await db.commit()
                assert (await approve_payment(1, operator, db)).status_code == 303
                assert company.is_active and company.payment_status == "approved"

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
                request = Request({"type": "http", "session": {"pending_business_id": 2},
                                   "headers": [(b"accept", b"application/json")]})
                with patch("routers.auth.creem.api", provider), patch(
                    "routers.auth.creem.charges",
                    return_value=(Charge("prod_setup", 13698, False), Charge("prod_monthly", 16742, True)),
                ):
                    denied = await creem_pay(1, request, db)
                    assert json.loads(denied.body)["location"] == "/login"
                    provider.assert_not_awaited()
                    request.session["pending_business_id"] = 1
                    checked = await creem_pay(1, request, db, verify_only=True)
                    assert json.loads(checked.body)["location"] == "/pending-activation/1"
                    provider.assert_awaited_once_with("GET", "checkouts", params={"checkout_id": "ch_setup"})
                    redirect = await creem_pay(1, request, db)

                assert json.loads(redirect.body)["location"] == "https://creem.io/checkout/ch_monthly"
                assert (await db.get(CreemPayment, "setup")).paid
                assert not (await db.get(CreemPayment, "monthly")).paid
                assert not company.is_active

    asyncio.run(scenario())
