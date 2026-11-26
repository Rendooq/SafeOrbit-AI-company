"""The workspaces and marketplace share real persistence, calendar and access controls."""
import asyncio
import csv
import hashlib
import hmac
import io
import json
import re
import wave
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from test_regressions import api as _isolated_environment  # Set safe app config before imports.
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import get_db
from main import app
from models import Appointment, Base, Business, CreemPayment, Customer, Master, Service, User
from models_platform import CreemWorkspaceSubscription, MarketplaceVisit, PhoneChallenge, WorkspaceRecord
from services import marketplace as calendar, workspace_tools
from utils.auth import AttemptLimiter
from utils.security import hash_password


@asynccontextmanager
async def test_app():
    with TemporaryDirectory() as directory:
        filename = (Path(directory) / "platform.db").as_posix()
        engine = create_async_engine(f"sqlite+aiosqlite:///{filename}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def isolated():
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = isolated
        try:
            with ExitStack() as stack:
                limits = {
                    "routers.auth.login_limiter": AttemptLimiter(),
                    "routers.auth.registration_limiter": AttemptLimiter(limit=6, window=300),
                    "routers.marketplace.LOGIN_LIMIT": AttemptLimiter(limit=12, window=300),
                    "routers.marketplace.SIGNUP_LIMIT": AttemptLimiter(limit=8, window=600),
                    "services.phone_auth.PER_ADDRESS": AttemptLimiter(limit=20, window=600),
                    "services.phone_auth.PER_NUMBER": AttemptLimiter(limit=6, window=600),
                }
                for path, limiter in limits.items():
                    stack.enter_context(patch(path, limiter))
                async with (
                    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as owner,
                    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as guest,
                ):
                    yield owner, guest, sessions
        finally:
            app.dependency_overrides.pop(get_db, None)
            await engine.dispose()


test_app.__test__ = False


def csrf(client):
    return {"x-csrf-token": client.cookies["so_csrf"]}


async def post(client, path, data):
    return await client.post(path, data=data, headers=csrf(client))


async def seed(sessions):
    encoded = hash_password("correct horse battery staple")
    async with sessions() as db:
        db.add_all([Business(id=1, name="North Barber", type="barbershop"),
                    Business(id=2, name="Other Workshop", type="other", plan_type="custom")])
        await db.flush()
        db.add_all([User(id=1, username="+380671111111", password=encoded, role="owner", business_id=1),
                    User(id=2, username="+380672222222", password=encoded, role="owner", business_id=2),
                    Master(id=1, name="Марко", business_id=1),
                    Service(id=1, name="Стрижка", price=650, duration=45, business_id=1)])
        await db.commit()


def test_signup_forces_constructor_price_and_workspace_checks_module_entitlements():
    async def scenario():
        async with test_app() as (owner, guest, sessions):
            await seed(sessions)
            response = await guest.get("/register?industry=other")
            assert "€19.80" in response.text
            signup = await post(guest, "/register", {"name": "Custom", "type": "other", "plan_type": "plan1",
                "registration_flow": "access", "phone": "+380679999999", "password": "valid password", "terms_accepted": "yes"})
            assert signup.status_code == 303, signup.text
            activation = await guest.get(signup.headers["location"])
            assert "€19.80" in activation.text
            async with sessions() as db:
                account = await db.scalar(select(Business).where(Business.name == "Custom"))
                assert account.plan_type == "custom" and not account.is_active
            await owner.get("/login")
            await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})
            assert (await owner.get("/workspace/module/reconcile")).status_code == 404
            assert (await owner.get("/workspace/listing")).status_code == 200
            await post(owner, "/login", {"username": "+380672222222", "password": "correct horse battery staple"})
            saved = await post(owner, "/workspace/layout", {"layout": ["reconcile", "notes"], "title": "My workspace",
                "accent": "fern", "width": "wide", "spacing": "compact"})
            assert saved.status_code == 303, saved.text
            space = await owner.get("/workspace")
            assert "accent-fern spacing-compact" in space.text and "My workspace" in space.text
            result = await post(owner, "/workspace/module/reconcile", {"title": "Check ledger",
                "first": "ttn;amount\n12345;450\n54321;780", "second": "ttn;amount\n12345;400"})
            assert result.status_code == 303, result.text
            report = await owner.get(result.headers["location"])
            assert "Немає виплати" in report.text and "830.00 грн" in report.text
            async with sessions() as db:
                record = await db.scalar(select(WorkspaceRecord).where(WorkspaceRecord.module == "reconcile"))
            csv_response = await owner.get(f"/workspace/records/{record.id}/export")
            assert ["54321", "780.00", "0.00", "780.00", "Немає виплати"] in list(csv.reader(io.StringIO(csv_response.text)))
            await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})
            assert (await owner.get(f"/workspace/records/{record.id}/export")).status_code == 404
    asyncio.run(scenario())


def test_public_listing_real_slots_sms_book_move_cancel_and_verified_reviews():
    async def scenario():
        async with test_app() as (owner, guest, sessions):
            await seed(sessions)
            await owner.get("/login")
            assert (await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})).status_code == 303
            form = await owner.get("/workspace/listing")
            assert form.status_code == 200, form.text
            publish = await post(owner, "/workspace/listing", {"city": "Київ", "address": "Хрещатик 1", "description": "Стрижки",
                "opens": "09:00", "closes": "18:00", "days": list("0123456"), "published": "yes"})
            assert publish.status_code == 303, publish.text
            tomorrow = str(calendar.now().date() + timedelta(days=1))
            directory = await guest.get("/maistry", params={"city": "київ", "q": "марко", "day": tomorrow, "max_price": "750"})
            assert directory.status_code == 200 and "North Barber" in directory.text
            assert (await guest.get("/maistry?max_price=")).status_code == 200
            assert (await guest.post("/maistry/register", data={"phone": "+380673333333"})).status_code == 403
            sms = AsyncMock(return_value=(True, "ok"))
            with patch.dict("os.environ", {"MARKETPLACE_SMS_TOKEN": "isolated"}), patch("services.phone_auth.send_sms", sms):
                issued = await post(guest, "/maistry/register", {"phone": "067 333 33 33"})
            assert issued.status_code == 303, issued.text
            code = re.search(r"\b[0-9]{6}\b", sms.call_args.args[-1])[0]
            signed_in = await post(guest, "/maistry/verify", {"code": code, "name": "Тарас", "password": "customer password"})
            assert signed_in.status_code == 303, signed_in.text
            shop = await guest.get(f"/maistry/zaklad/1?day={tomorrow}&service_id=1&master_id=1")
            assert shop.status_code == 200 and 'value="10:00"' in shop.text
            basic = {"day": tomorrow, "service_id": 1, "master_id": 1, "hour": "10:00"}
            with patch("routers.marketplace.send_new_appointment_notifications", AsyncMock()):
                assert (await post(guest, "/maistry/zaklad/1/book", basic)).status_code == 303
                assert (await post(guest, "/maistry/zaklad/1/book", {**basic, "hour": "10:15"})).status_code == 409
                async with sessions() as db:
                    visit = await db.scalar(select(MarketplaceVisit))
                    identifier = visit.appointment_id
                assert (await post(guest, "/maistry/zaklad/1/book", {**basic, "hour": "11:00", "visit_id": identifier})).status_code == 303
                assert (await post(guest, f"/maistry/visits/{identifier}/review", {"rating": "5"})).status_code == 409
                second = await post(guest, "/maistry/zaklad/1/book", basic)
                assert second.status_code == 303, second.text
                async with sessions() as db:
                    second_id = await db.scalar(select(Appointment.id).order_by(Appointment.id.desc()).limit(1))
                assert (await post(guest, f"/maistry/visits/{second_id}/cancel", {})).status_code == 303
            async with sessions() as db:
                appointment = await db.get(Appointment, identifier)
                assert appointment.appointment_time.hour == 11 and appointment.source == "marketplace"
                appointment.status, appointment.appointment_time = "completed", calendar.now() - timedelta(hours=2)
                await db.commit()
            assert (await post(guest, f"/maistry/visits/{identifier}/review", {"rating": "5", "comment": "Чудовий візит"})).status_code == 303
            assert (await post(guest, f"/maistry/visits/{identifier}/review", {"rating": "5"})).status_code == 409
            assert "Чудовий візит" in (await guest.get("/maistry/zaklad/1")).text
            assert (await post(owner, f"/maistry/visits/{identifier}/cancel", {})).status_code == 401
            assert "Стрижка" in (await guest.get("/maistry/account")).text
            saved = await post(guest, "/maistry/zaklad/1/favorite", {"favorite": "yes"})
            assert saved.status_code == 303
            assert "North Barber" in (await guest.get("/maistry?saved=1&category=barber")).text
            assert "North Barber" not in (await guest.get("/maistry?category=nails")).text
            unsaved = await post(guest, "/maistry/zaklad/1/favorite", {"favorite": "no"})
            assert unsaved.status_code == 303
            assert "North Barber" not in (await guest.get("/maistry?saved=1")).text
            assert (await post(guest, "/maistry/logout", {})).status_code == 303
            with patch.dict("os.environ", {"AUTH_SMS_TOKEN": "isolated"}), patch("services.phone_auth.send_sms", sms):
                logged = await post(guest, "/maistry/login", {"phone": "0673333333", "password": "customer password"})
            assert logged.headers["location"] == "/maistry/login/verify"
            assert (await guest.get("/maistry/account")).headers["location"] == "/maistry/login"
            login_code = re.search(r"\b[0-9]{6}\b", sms.call_args.args[-1])[0]
            assert (await post(guest, "/maistry/login/verify", {"code": "999999" if login_code != "999999" else "999998"})).status_code == 422
            assert (await post(guest, "/maistry/login/verify", {"code": login_code})).headers["location"] == "/maistry/account"
            assert (await post(guest, "/maistry/login/verify", {"code": login_code})).status_code == 422
    asyncio.run(scenario())


def test_catalog_only_renders_publish_action_for_eligible_business_accounts():
    async def scenario():
        async with test_app() as (owner, customer, sessions):
            await seed(sessions)
            path = "/workspace/listing"
            action = f'href="{path}"'

            anonymous = await customer.get("/maistry")
            assert anonymous.status_code == 200 and action not in anonymous.text
            await customer.get("/maistry/register")
            assert (await post(customer, "/maistry/register", {
                "phone": "+380677772103", "name": "Клієнт", "password": "customer password"
            })).status_code == 303
            signed_in = await customer.get("/maistry")
            assert action not in signed_in.text and "Мої візити" in signed_in.text
            assert (await customer.get(path)).status_code == 403

            await owner.get("/login")
            await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})
            assert action in (await owner.get("/maistry")).text
            settings = await owner.get(path)
            assert settings.status_code == 200 and 'href="/workspace"' in settings.text

            for role, industry, expected_status in (("admin", "barbershop", 200), ("admin", "clinic", 404),
                                                     ("master", "barbershop", 403)):
                async with sessions() as db:
                    (await db.get(User, 1)).role = role
                    (await db.get(Business, 1)).type = industry
                    await db.commit()
                catalog = await owner.get("/maistry")
                assert catalog.status_code == 200
                assert (action in catalog.text) == (expected_status == 200)
                assert (await owner.get(path)).status_code == expected_status

            await owner.get("/maistry/register")
            assert (await post(owner, "/maistry/register", {
                "phone": "+380677772104", "name": "Клієнт і співробітник", "password": "customer password"
            })).status_code == 303
            async with sessions() as db:
                (await db.get(Business, 1)).is_active = False
                await db.commit()
            assert action not in (await owner.get("/maistry")).text
            assert (await owner.get("/maistry/account")).status_code == 200
    asyncio.run(scenario())


def test_file_tools_parse_real_documents_and_escape_spreadsheet_formulas():
    from pypdf import PdfWriter

    out = io.BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=595.28, height=841.89)
    pdf.write(out)
    assert "нормі" in workspace_tools.preflight(out.getvalue(), "210", "297", "0")["rows"][0][-1]
    assert "виліт" in workspace_tools.preflight(out.getvalue(), "210", "297", "3")["rows"][0][-1]
    assert "'=A1" in workspace_tools.csv_report(["Test"], [["=A1"]])
    cut = workspace_tools.cutting("part;width;height;qty;rotate\nA;49;50;2;0", "100", "50", "3")
    assert [line[0] for line in cut["rows"]] == [1, 2]
    assert "не збігається" in workspace_tools.feeds(
        "<rss><channel><item><id>A</id><price>10.00 UAH</price><availability>in_stock</availability></item></channel></rss>",
        "id;price;availability\nA;11.00 UAH;in_stock"
    )["rows"][0][-1]
    import pytest
    with pytest.raises(workspace_tools.ToolError):
        workspace_tools.feeds('<!DOCTYPE a [<!ENTITY payload "x">]><rss>&payload;</rss>')


def test_constructor_table_proposal_and_revocable_book_sharing():
    async def scenario():
        async with test_app() as (owner, guest, sessions):
            await seed(sessions)
            await owner.get("/login")
            await post(owner, "/login", {"username": "+380672222222", "password": "correct horse battery staple"})
            created = await post(owner, "/workspace/tables", {"title": "Work", "name": ["Title", "Amount"], "kind": ["text", "number"]})
            assert created.status_code == 303, created.text
            path = created.headers["location"]
            assert (await post(owner, path + "/rows", {"value_0": "=HYPERLINK()", "value_1": "42.5"})).status_code == 303
            export = await owner.get(path + "/export")
            assert "'=HYPERLINK()" in export.text and "42.50" in export.text
            assert (await guest.get(path + "/export")).status_code == 403
            proposal = await post(owner, "/workspace/module/extras", {"title": "Change", "first": "item;cost\nPaint;400", "days": "1"})
            assert proposal.status_code == 303, proposal.text
            proposal_page = await owner.get(proposal.headers["location"])
            link = re.search(r'href="(/proposals/[^"]+)"', proposal_page.text)[1]
            assert (await guest.get(link + "z")).status_code == 404
            public_proposal = await guest.get(link)
            assert public_proposal.status_code == 200 and 'href="/workspace"' not in public_proposal.text
            assert (await post(guest, link, {"name": "Approval", "action": "approved"})).status_code == 303
            assert "Погоджено" in (await guest.get(link)).text

            sound = io.BytesIO()
            with wave.open(sound, "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(b"\0" * 800)
            book = await owner.post("/workspace/module/book", data={"title": "Story", "body": "Chapter text"},
                                    files={"file": ("voice.wav", sound.getvalue(), "audio/wav")}, headers=csrf(owner))
            assert book.status_code == 303, book.text
            assert (await post(owner, "/workspace/book/share", {"share": "yes"})).status_code == 303
            print_view = await owner.get("/workspace/book/print")
            qr = re.search(r'src="(/books/[^"]+/qr/\d+)"', print_view.text)[1]
            assert (await guest.get(qr)).content.startswith(b"\x89PNG")
            assert (await guest.get(qr.replace("/qr/", "/asset/"))).content == sound.getvalue()
            assert (await post(owner, "/workspace/book/share", {"share": "no"})).status_code == 303
            assert (await guest.get(qr)).status_code == 404
    asyncio.run(scenario())


def test_creem_events_require_signature_and_handle_ordered_subscription_updates():
    async def scenario():
        async with test_app() as (owner, _, sessions):
            await seed(sessions)
            async with sessions() as db:
                db.add(CreemPayment(id="order-unit", business_id=2, product_id="prod_test", cents=1980, recurring=True,
                                    checkout_id="ch_test", paid=False))
                await db.commit()
            key = "isolated-webhook"
            first = int(datetime.now(timezone.utc).timestamp() * 1000)
            end = (datetime.now(timezone.utc) + timedelta(days=27)).isoformat()
            checkout = {"id": "ch_test", "request_id": "order-unit", "status": "completed", "mode": "prod",
                         "product": {"id": "prod_test"}, "subscription": {"id": "sub_test", "current_period_end_date": end},
                         "order": {"status": "paid", "currency": "EUR", "sub_total": 1980, "amount_paid": 1980, "amount_due": 1980}}
            sub = {"id": "sub_test", "product": {"id": "prod_test"}, "current_period_end_date": end}

            async def send(kind, payload, created, signed=True):
                raw = json.dumps({"eventType": kind, "object": payload, "created_at": created}).encode()
                signature = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest() if signed else "0" * 64
                return await owner.post("/billing/creem/events", content=raw, headers={"creem-signature": signature})

            with patch.dict("os.environ", {"CREEM_WEBHOOK_SECRET": key, "CREEM_ENABLED": "1", "CREEM_API_KEY": "isolated-key"}):
                assert (await send("checkout.completed", checkout, first, signed=False)).status_code == 401
                assert (await send("checkout.completed", {**checkout, "mode": "test"}, first)).status_code == 422
                assert (await send("checkout.completed", checkout, first)).status_code == 204
                async with sessions() as db:
                    assert (await db.get(CreemPayment, "order-unit")).paid
                    assert (await db.get(CreemWorkspaceSubscription, 2)).provider_id == "sub_test"
                assert (await send("subscription.paused", sub, first+5)).status_code == 204
                assert (await send("subscription.paid", sub, first+1)).status_code == 204
                async with sessions() as db:
                    assert not (await db.get(Business, 2)).is_active
                assert (await send("subscription.paid", sub, first+8)).status_code == 204
                async with sessions() as db:
                    assert (await db.get(Business, 2)).is_active
    asyncio.run(scenario())


def test_business_signup_and_password_login_both_require_bound_sms():
    async def scenario():
        async with test_app() as (owner, stranger, sessions):
            await seed(sessions)
            sms = AsyncMock(return_value=(True, "accepted"))
            payload = {"name": "Second factor", "type": "other", "plan_type": "plan1", "registration_flow": "access",
                       "phone": "+380674445566", "password": "team member pw", "terms_accepted": "yes"}
            with patch.dict("os.environ", {"AUTH_SMS_TOKEN": "isolated"}), patch("services.phone_auth.send_sms", sms):
                html = await owner.get("/register?industry=other")
                assert 'name="sms_code"' in html.text
                assert (await post(owner, "/register", payload)).headers["location"] == "/register?error=sms"
                result = await owner.post("/register/phone", data={"phone": payload["phone"]},
                                           headers={**csrf(owner), "accept": "application/json"})
                assert result.status_code == 200
                signup = re.search(r"\b[0-9]{6}\b", sms.call_args.args[-1])[0]
                await stranger.get("/register")
                assert (await post(stranger, "/register", {**payload, "sms_code": signup})).headers["location"] == "/register?error=sms"
                assert (await post(owner, "/register", {**payload, "phone": "+380674445567", "sms_code": signup})).headers["location"] == "/register?error=sms"
                created = await post(owner, "/register", {**payload, "sms_code": signup})
                assert created.headers["location"].startswith("/pending-activation/")
                assert (await post(owner, "/register", {**payload, "sms_code": signup})).headers["location"] == "/register?error=sms"
                signin = await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})
                assert signin.headers["location"] == "/login/verify"
                assert (await owner.get("/workspace")).headers["location"] == "/login"
                verification = re.search(r"\b[0-9]{6}\b", sms.call_args.args[-1])[0]
                assert (await post(stranger, "/login/verify", {"code": verification})).status_code == 422
                assert (await post(owner, "/login/verify", {"code": verification})).headers["location"] == "/admin"
                assert (await owner.get("/workspace")).status_code == 200
                assert (await post(owner, "/login/verify", {"code": verification})).status_code == 422
            async with sessions() as db:
                business = await db.scalar(select(Business).where(Business.name == "Second factor"))
                assert business and business.plan_type == "custom"
    asyncio.run(scenario())


def test_sms_gateway_accepts_documented_queue_response():
    from types import SimpleNamespace
    from services.sms import send_sms

    async def scenario():
        def provider(request):
            assert json.loads(request.content)["recipients"] == ["380674445566"]
            return httpx.Response(200, json={"response_code": 800, "response_result": [
                {"response_code": 0, "phone": "380674445566", "message_id": "accepted"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            account = SimpleNamespace(id="example", sms_token="secret-for-test", sms_sender_id="SafeOrbit")
            assert (await send_sms(client, account, "+380674445566", "test"))[0]
    asyncio.run(scenario())


def test_password_signup_and_booking_work_without_sms_and_do_not_inherit_crm_history():
    async def scenario():
        async with test_app() as (owner, guest, sessions):
            await seed(sessions)
            number = "+380677775551"
            async with sessions() as db:
                db.add(Customer(id=90, business_id=1, phone_number=number, name="Existing private CRM client"))
                await db.flush()
                db.add(Appointment(business_id=1, customer_id=90, master_id=1, service_type="Private past visit",
                                   appointment_time=calendar.now()-timedelta(days=1), cost=650, status="completed"))
                await db.commit()
            await owner.get("/login")
            with patch.dict("os.environ", {"ENVIRONMENT": "production", "AUTH_SMS_TOKEN": "", "MARKETPLACE_SMS_TOKEN": ""}):
                signin = await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})
                assert signin.headers["location"] == "/admin"
                settings = await post(owner, "/workspace/listing", {"city": "Київ", "address": "Хрещатик 1",
                    "opens": "09:00", "closes": "19:00", "days": list("0123456"), "published": "yes"})
                assert settings.status_code == 303
                registration = await guest.get("/maistry/register")
                assert 'name="password"' in registration.text and 'name="name"' in registration.text
                assert "Отримати код SMS" not in registration.text
                password = "marketplace password"
                signup = await post(guest, "/maistry/register", {"phone": number, "name": "New customer",
                    "password": password, "next": "/maistry/zaklad/1"})
                assert signup.headers["location"] == "/maistry/zaklad/1"
                profile = await guest.get("/maistry/account")
                assert "Private past visit" not in profile.text
                tomorrow = str(calendar.now().date()+timedelta(days=1))
                book = {"day": tomorrow, "service_id": 1, "master_id": 1, "hour": "10:00"}
                alert = AsyncMock()
                with patch("routers.marketplace.send_new_appointment_notifications", alert):
                    assert (await post(guest, "/maistry/zaklad/1/book", book)).status_code == 303
                    assert (await post(guest, "/maistry/zaklad/1/book", {**book, "hour": "11:00"})).status_code == 303
                assert alert.call_args.kwargs["contact_phone"] == number + " (номер не підтверджено)"
                async with sessions() as db:
                    bookings = (await db.scalars(select(Appointment).where(Appointment.source == "marketplace"))).all()
                    assert len(bookings) == 2 and bookings[0].customer_id != 90
                    assert bookings[0].customer_id == bookings[1].customer_id
                    contact = await db.get(Customer, bookings[0].customer_id)
                    assert contact.phone_number == "" and number in contact.notes
                    assert (await db.get(Customer, 90)).name == "Existing private CRM client"
                assert (await post(guest, "/maistry/logout", {})).status_code == 303
                assert (await post(guest, "/maistry/login", {"phone": number, "password": "wrong password"})).status_code == 401
                authenticated = await post(guest, "/maistry/login", {"phone": number, "password": password})
                assert authenticated.headers["location"] == "/maistry/account"
                assert "Стрижка" in (await guest.get("/maistry/account")).text

                business_page = await owner.get("/register")
                assert 'name="sms_code"' not in business_page.text
                company = await post(owner, "/register", {"name": "New business", "phone": "+380677775552",
                    "password": "business password", "type": "barbershop", "plan_type": "plan1",
                    "terms_accepted": "yes", "registration_flow": "access"})
                assert company.headers["location"].startswith("/pending-activation/")
    asyncio.run(scenario())


def test_sms_cooldown_attempt_limit_and_expiry():
    from services import phone_auth

    async def scenario():
        async with test_app() as (_, guest, sessions):
            mocked = AsyncMock(return_value=(True, "accepted"))
            number = "+380677775500"
            async def insert_code():
                return await post(guest, "/maistry/register", {"phone": number})
            data = {"name": "Test", "password": "safe password"}
            await guest.get("/maistry/register")
            with patch.dict("os.environ", {"AUTH_SMS_TOKEN": "isolated"}), patch("services.phone_auth.send_sms", mocked):
                assert (await insert_code()).status_code == 303
                assert (await insert_code()).status_code == 429 and mocked.await_count == 1
                correct = re.search(r"\b[0-9]{6}\b", mocked.call_args.args[-1])[0]
                invalid = "000000" if correct != "000000" else "000001"
                for _ in range(5):
                    assert (await post(guest, "/maistry/verify", {**data, "code": invalid})).status_code == 422
                assert (await post(guest, "/maistry/verify", {**data, "code": correct})).status_code == 422
                async with sessions() as db:
                    row = await db.get(PhoneChallenge, (number, phone_auth.SIGNUP_CUSTOMER))
                    assert row.attempts == 5
                    row.sent_at = phone_auth.now() - timedelta(minutes=2)
                    await db.commit()
                assert (await insert_code()).status_code == 303 and mocked.await_count == 2
                async with sessions() as db:
                    row = await db.get(PhoneChallenge, (number, phone_auth.SIGNUP_CUSTOMER))
                    row.expires_at = phone_auth.now() - timedelta(seconds=1)
                    await db.commit()
                expired = re.search(r"\b[0-9]{6}\b", mocked.call_args.args[-1])[0]
                assert (await post(guest, "/maistry/verify", {**data, "code": expired})).status_code == 422
    asyncio.run(scenario())
