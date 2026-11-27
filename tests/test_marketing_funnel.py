import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from test_platform import post, test_app

from models import Business, CampaignVisit, CreemPayment
from routers import auth
from routers.superadmin import campaign_report, creem_check
from services import creem, marketing_funnel


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
                admin = SimpleNamespace(role="superadmin")
                rendered = await campaign_report(user=admin, db=db)
                assert "slot_recovery" in rendered.body.decode()
                assert rendered.headers["cache-control"] == "private, no-store"

            directory = "/?utm_source=osyo&utm_medium=referral&utm_campaign=safeorbit&utm_content=product_page"
            assert (await stranger.get(directory)).status_code == 200
            async with sessions() as db:
                rows, totals = await marketing_funnel.report(db, 30)
                assert [list(row) for row in rows] == [
                    ["linkedin", "slot_recovery", 1, 1, 1, 1],
                    ["osyo", "safeorbit", 1, 0, 0, 0],
                ]
                assert totals == [2, 1, 1, 1]

    with patch.dict("os.environ", {"AUTH_SMS_TOKEN": "", "MARKETPLACE_SMS_TOKEN": "", "CREEM_ENABLED": "0"}):
        asyncio.run(scenario())


def test_creem_check_is_private_and_reports_prices_without_exposing_product_ids():
    async def scenario():
        async with test_app() as (visitor, _, sessions):
            assert (await visitor.get("/superadmin/creem-check")).status_code == 303
            product = {"id": "prod_privateTest", "currency": "EUR", "price": 1980,
                       "status": "active", "billing_type": "recurring", "billing_period": "every-month"}
            async with sessions() as db:
                admin = SimpleNamespace(role="superadmin", id=48173)
                with patch.object(creem, "get_product", AsyncMock(return_value=product)) as provider:
                    response = await creem_check(user=admin, db=db)
                    provider.assert_awaited_once_with("prod_privateTest")
                    assert "Підтверджено в Creem" in response.body.decode()
                    assert "prod_privateTest" not in response.body.decode()
                    product["price"] = 1990
                    response = await creem_check(user=admin, db=db)
                    assert "Параметри продукту відрізняються" in response.body.decode()

    with patch.dict("os.environ", {
        "CREEM_ENABLED": "1", "CREEM_API_KEY": "local_diagnostic",
        "CREEM_WEBHOOK_SECRET": "local_diagnostic",
        "CREEM_ONLINE_TERMS_VERSION": "2026-11-26",
        "CREEM_BUSINESS_MONTHLY_V2_PRODUCT_ID": "", "CREEM_PRO_MONTHLY_PRODUCT_ID": "",
        "CREEM_COMMERCE_MONTHLY_PRODUCT_ID": "", "CREEM_WORKSHOP_MONTHLY_PRODUCT_ID": "",
        "CREEM_CUSTOM_MONTHLY_PRODUCT_ID": "prod_privateTest",
    }):
        asyncio.run(scenario())
