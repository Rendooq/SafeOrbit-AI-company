import asyncio
from datetime import date, datetime

from sqlalchemy import select
from starlette.requests import Request

from test_regressions import api
from models import Appointment, Business, Master, User
from routers import admin, dashboard


def test_agenda_save_returns_to_the_new_date_and_specialist():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                owner = await db.get(User, 1)
                added = await dashboard.add_appointment(
                    phone="111", name="Guest", date="2026-12-07", time="09:30",
                    service="Visit", custom_service="", cost="120", master_id="1",
                    delivery_address=None, user=owner, db=db, overview_period=30,
                    overview_specialist=1,
                )
                assert added.headers["location"] == "/admin?msg=added&day=2026-12-07&specialist=1&period=30#day-agenda"
                visit = await db.scalar(select(Appointment))
                saved = await dashboard.update_appointment(
                    id=visit.id, date="2026-12-08", time="11:00", cost="120", master_id="1",
                    delivery_address=None, ttn=None, delivery_status="pending", status="confirmed",
                    user=owner, db=db, overview_period=7,
                )
                assert saved.headers["location"] == "/admin?msg=saved&day=2026-12-08&specialist=0&period=7#day-agenda"
                assert dashboard.saved_agenda("saved", visit, None, 1).headers["location"] == "/admin?msg=saved"
    asyncio.run(scenario())


def test_specialist_agenda_and_legacy_calendar_share_scope():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                staff = await db.get(Master, 1)
                staff.role = "Стиліст"
                db.add(Master(id=3, business_id=1, name="Colleague"))
                user = User(username="personal", password="unused", role="master", business_id=1, master_id=1)
                db.add(user)
                await db.flush()
                for business, master, customer, day, service, cost in [
                    (1, 1, 1, 7, "Assigned visit", 124.50),
                    (1, 3, 1, 7, "Another specialist", 1000),
                    (1, 3, 1, 8, "Colleague only day", 900),
                    (2, 2, 2, 7, "Another workspace", 750),
                ]:
                    db.add(Appointment(business_id=business, master_id=master, customer_id=customer,
                        appointment_time=datetime(2026,12,day,12), service_type=service, cost=cost, status="completed"))
                await db.commit()
                user.business = await db.get(Business, 1)
                view = await dashboard.owner_dash(Request({"type":"http","session":{}}), user, db, day=date(2026,12,7))
                assert "Assigned visit" in view and "124.50" in view
                for hidden in ["Another specialist", "Another workspace", "Colleague only day"]:
                    assert hidden not in view
                assert await admin.get_calendar_data("2026-12-01","2027-01-01",user,db) == [{"date":"2026-12-07"}]
                details = await admin.get_day_details("2026-12-07", user, db)
                assert [row["service"] for row in details] == ["Assigned visit"]
    asyncio.run(scenario())
