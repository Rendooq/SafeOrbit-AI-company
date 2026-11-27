import asyncio
from unittest.mock import patch

from sqlalchemy import select
from test_platform import post, test_app

from models import Business, CampaignVisit, CreemPayment
from routers import auth
from routers.superadmin import campaign_report
from services import marketing_funnel


def test_funnel_groups_registered_visits_and_counts_only_confirmed_monthly_payments():
    async def scenario():
        async with test_app() as (visitor, stranger, sessions):
            campaign = auth.SLOT_RECOVERY_PAGE + "?utm_source=linkedin&utm_medium=organic_social&utm_campaign=slot_recovery"
            assert (await stranger.get(campaign, headers={"User-Agent": "LinkedInBot"})).status_code == 200
            landing = await visitor.get(campaign)
            assert landing.status_code == 200
            assert 'href="/rozbir-rozkladu"' in landing.text
            assert (await visitor.get(campaign)).status_code == 200
            with patch.object(auth.demo_workspaces, "start", return_value="local-marketing-demo"):
                assert (await visitor.get("/login-demo")).headers["location"] == "/admin"
            signup = await visitor.get("/register?industry=other")
            assert 'name="utm_source" value="linkedin"' in signup.text
            response = await post(visitor, "/register", {
                "name": "Funnel Studio", "type": "other", "phone": "+380679991234",
                "password": "valid local test password", "registration_flow": "access",
                "terms_accepted": "yes", "plan_type": "plan1", "utm_source": "linkedin",
            })
            assert response.status_code == 303
            assert (await stranger.get("/superadmin/campaigns")).status_code == 303
            async with sessions() as db:
                visit = (await db.scalars(select(CampaignVisit))).one()
                workspace = await db.get(Business, visit.business_id)
                assert workspace.name == "Funnel Studio"
                rows, totals = await marketing_funnel.report(db, 30)
                assert list(rows[0]) == ["linkedin", "slot_recovery", 1, 1, 0, 0]
                assert totals == [1, 1, 0, 0]

                db.add(CreemPayment(id="funnel-setup", business_id=workspace.id, product_id="prod_setup",
                                    cents=1800, recurring=False, checkout_id="ch_setup", paid=True))
                await db.commit()
                assert (await marketing_funnel.report(db, 30))[1] == [1, 1, 1, 0]

                db.add(CreemPayment(id="funnel-monthly", business_id=workspace.id, product_id="prod_custom",
                                    cents=1980, recurring=True, checkout_id="ch_custom", paid=True))
                await db.commit()
                assert (await marketing_funnel.report(db, 30))[1] == [1, 1, 1, 1]
                admin = type("Admin", (), {"role": "superadmin"})()
                rendered = await campaign_report(user=admin, db=db)
                assert "slot_recovery" in rendered.body.decode()
                assert rendered.headers["cache-control"] == "private, no-store"

    with patch.dict("os.environ", {"AUTH_SMS_TOKEN": "", "MARKETPLACE_SMS_TOKEN": "", "CREEM_ENABLED": "0"}):
        asyncio.run(scenario())
