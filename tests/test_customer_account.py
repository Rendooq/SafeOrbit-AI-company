import asyncio
import io
import re
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from sqlalchemy import select

from test_platform import csrf, post, seed, test_app
from main import app
from models import Appointment
from models_platform import MarketplaceVoucher
from services import marketplace as calendar


PHONE = "+380677721234"
PASSWORD = "customer password"


async def signup(client, phone=PHONE):
    await client.get("/maistry/register")
    response = await post(client, "/maistry/register", {"phone": phone, "name": "Анна Коваль", "password": PASSWORD})
    assert response.headers["location"] == "/maistry/account"


def test_customer_account_profile_photo_password_and_private_sessions():
    async def scenario():
        async with test_app() as (_, customer, sessions):
            await signup(customer)
            result = await customer.get("/maistry/account")
            assert result.status_code == 200
            assert "Анна Коваль" in result.text and "Вітаємо" in result.text
            for section in ("visits", "reviews", "favorites", "vouchers", "settings"):
                assert (await customer.get(f"/maistry/account/{section}")).status_code == 200
            changed = await post(customer, "/maistry/account/settings/profile", {"name": "  Олена   Коваль "})
            assert changed.headers["location"] == "/maistry/account/settings?done=profile"
            assert "Олена Коваль" in (await customer.get("/maistry/account")).text
            payload = io.BytesIO()
            Image.new("RGB", (60, 60), "#603ecd").save(payload, "PNG")
            saved = await customer.post("/maistry/account/settings/avatar", files={"file": ("avatar.png", payload.getvalue(), "image/png")},
                                        headers=csrf(customer))
            assert saved.status_code == 303
            assert (await customer.get("/maistry/account/avatar")).headers["content-type"] == "image/jpeg"
            archived_session = customer.cookies["session"]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as separate:
                assert (await separate.get("/maistry/account/avatar")).status_code == 404
                separate.cookies.set("session", archived_session)
                assert (await separate.get("/maistry/account")).status_code == 200
                change = {"current_password": PASSWORD, "new_password": "changed password", "repeat_password": "changed password"}
                assert (await post(customer, "/maistry/account/settings/password", {**change, "current_password": "incorrect"})).status_code == 422
                assert (await post(customer, "/maistry/account/settings/password", change)).status_code == 303
                assert (await separate.get("/maistry/account")).headers["location"] == "/maistry/login"
            assert (await customer.get("/maistry/account")).status_code == 200
            assert (await post(customer, "/maistry/account/settings/avatar", {"remove": "yes"})).status_code == 303
            assert (await customer.get("/maistry/account/avatar")).status_code == 404
            await post(customer, "/maistry/logout", {})
            assert (await post(customer, "/maistry/login", {"phone": PHONE, "password": PASSWORD})).status_code == 401
            assert (await post(customer, "/maistry/login", {"phone": PHONE, "password": "changed password"})).status_code == 303
    asyncio.run(scenario())


def test_merchant_voucher_from_issue_through_claim_booking_cancel_and_reuse():
    async def scenario():
        async with test_app() as (owner, customer, sessions):
            await seed(sessions)
            await owner.get("/login")
            await post(owner, "/login", {"username": "+380671111111", "password": "correct horse battery staple"})
            assert (await post(owner, "/workspace/listing", {"city": "Київ", "address": "Хрещатик 1",
                "opens": "09:00", "closes": "18:00", "days": list("0123456"), "published": "yes"})).status_code == 303
            await signup(customer)
            merchant = "/workspace/listing/vouchers"
            path = "/maistry/account/vouchers"
            assert (await customer.get(merchant)).status_code == 403
            expires = str(calendar.now().date()+timedelta(days=2))
            issued = await post(owner, merchant, {"title": "Знижка 150", "value": "150", "ends": expires})
            assert issued.headers["location"] == merchant
            page = await owner.get(merchant)
            code = re.search(r"[0-9A-F]{5}(?:-[0-9A-F]{5}){3}", page.text)[0]
            assert code not in (await owner.get(merchant)).text
            assert (await post(customer, path + "/claim", {"code": code.lower()})).headers["location"] == path + "?done=voucher"
            assert (await post(customer, path + "/claim", {"code": code})).status_code == 422
            assert "Знижка 150" in (await customer.get(path)).text
            async with sessions() as db:
                voucher_id = await db.scalar(select(MarketplaceVoucher.id))
            tomorrow = str(calendar.now().date()+timedelta(days=1))
            book_url = "/maistry/zaklad/1/book"
            payload = {"day": tomorrow, "service_id": 1, "master_id": 1, "hour": "10:00", "voucher_id": voucher_id}
            with patch("routers.marketplace.send_new_appointment_notifications", AsyncMock()):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
                    await signup(other, "+380677721235")
                    assert (await post(other, path + "/claim", {"code": code})).status_code == 422
                    assert (await post(other, book_url, payload)).status_code == 409
                options = await customer.get(f"/maistry/zaklad/1?day={tomorrow}&service_id=1&master_id=1")
                assert "500.00 грн після знижки" in options.text
                assert (await post(customer, book_url, payload)).status_code == 303
                assert (await post(customer, book_url, {**payload, "hour": "11:00"})).status_code == 409
                assert (await post(owner, merchant + f"/{voucher_id}/revoke", {})).status_code == 409
                async with sessions() as db:
                    visit = await db.scalar(select(Appointment).where(Appointment.source == "marketplace"))
                    assert visit.cost == 500
                    first_id = visit.id
                invalid_day = str(calendar.now().date()+timedelta(days=3))
                moved = await post(customer, book_url, {**payload, "day": invalid_day, "visit_id": first_id})
                assert moved.status_code == 409
                assert (await post(customer, book_url, {**payload, "hour": "11:00", "visit_id": first_id})).status_code == 303
                assert (await post(customer, f"/maistry/visits/{first_id}/cancel", {})).status_code == 303
                assert "Доступний" in (await customer.get(path)).text
                assert (await post(customer, book_url, {**payload, "hour": "11:00"})).status_code == 303
            async with sessions() as db:
                voucher = await db.get(MarketplaceVoucher, voucher_id)
                assert voucher.appointment_id != first_id
                visit = await db.get(Appointment, voucher.appointment_id)
                assert visit.cost == 500
                visit.status = "completed"
                await db.commit()
            assert "Використано" in (await customer.get(path)).text
    asyncio.run(scenario())
