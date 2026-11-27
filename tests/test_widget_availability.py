import asyncio
from datetime import datetime, time, timedelta

from test_platform import seed, test_app

from models import Appointment, Customer, Master
from services.marketplace import now


def test_public_widget_only_offers_times_that_fit_the_team_calendar():
    async def scenario():
        async with test_app() as (_, guest, sessions):
            await seed(sessions)
            day = now().date() + timedelta(days=1)
            async with sessions() as db:
                db.add_all([Master(id=2, name="Назар & Оля", business_id=1),
                            Master(id=3, name="Інший салон", business_id=2),
                            Customer(id=10, business_id=1, name="Клієнт", phone_number="+12025550109")])
                await db.flush()
                db.add_all([
                    Appointment(business_id=1, master_id=1, customer_id=10, service_type="Стрижка",
                                appointment_time=datetime.combine(day, time(10)), status="confirmed"),
                    Appointment(business_id=1, master_id=1, customer_id=10, service_type="Стрижка",
                                appointment_time=datetime.combine(day, time(11)), status="cancelled"),
                ])
                await db.commit()

            widget = await guest.get("/widget/1")
            assert widget.status_code == 200
            assert "Назар &amp; Оля" in widget.text

            query = {"day": day.isoformat(), "service": "Стрижка"}
            response = await guest.get("/widget/1/slots", params={**query, "master_id": 1})
            assert response.status_code == 200
            assert "no-store" in response.headers["cache-control"]
            available = set(response.json()["times"])
            assert {"09:00", "11:00"} <= available
            assert {"09:30", "10:00", "10:30"}.isdisjoint(available)

            colleague = await guest.get("/widget/1/slots", params={**query, "master_id": 2})
            assert "10:00" in colleague.json()["times"]
            unassigned = await guest.get("/widget/1/slots", params=query)
            assert "10:00" not in unassigned.json()["times"]
            foreign = await guest.get("/widget/1/slots", params={**query, "master_id": 3})
            assert foreign.status_code == 400

    asyncio.run(scenario())
