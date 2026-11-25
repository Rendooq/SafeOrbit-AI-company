"""The workspaces and marketplace share real persistence, calendar and access controls."""
import asyncio
import csv
import hashlib
import hmac
import io
import json
import re
import wave
from contextlib import asynccontextmanager
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
from models import Appointment, Base, Business, CreemPayment, Master, Service, User
from models_platform import CreemWorkspaceSubscription, MarketplaceVisit, WorkspaceRecord
from services import marketplace as calendar, workspace_tools
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
            with patch.dict("os.environ", {"MARKETPLACE_SMS_TOKEN": "isolated"}), patch("routers.marketplace.send_sms", sms):
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
            assert (await guest.get(link)).status_code == 200
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
