import asyncio
from datetime import date, datetime

from test_regressions import api

from models import Appointment, Business, Master, User
from routers.dashboard import export_reports, reports_page


def test_report_specialist_filters_trend_and_export_to_the_current_workspace():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                user = await db.get(User, 1)
                user.business = await db.get(Business, 1)
                db.add(Master(id=3, business_id=1, name="Other specialist"))
                db.add_all([
                    Appointment(business_id=1, customer_id=1, master_id=1, service_type="Selected service",
                                appointment_time=datetime(2026, 11, 23, 10), status="completed", cost=175),
                    Appointment(business_id=1, customer_id=1, master_id=3, service_type="Other service",
                                appointment_time=datetime(2026, 11, 23, 11), status="completed", cost=490),
                    Appointment(business_id=2, customer_id=2, master_id=2, service_type="Foreign service",
                                appointment_time=datetime(2026, 11, 23, 12), status="completed", cost=760),
                ])
                await db.commit()
                day = date(2026, 11, 23)
                report = await reports_page(day, day, user, db, specialist=1)
                assert all(text in report for text in (
                    "Динаміка доходу", "Результати команди", "Selected service", "175.00", "specialist=1",
                ))
                assert "Other service" not in report and "Foreign service" not in report
                report_all = await reports_page(day, day, user, db, specialist=0)
                assert "Other service" in report_all and "Foreign service" not in report_all
                csv = (await export_reports(day, day, user, db, specialist=1)).body.decode("utf-8-sig")
                assert "Selected service" in csv and "Other service" not in csv and "Foreign service" not in csv

    asyncio.run(scenario())
