"""Isolated regression coverage for redesigned frontend and authentication."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory
import io

from test_regressions import api
from sqlalchemy import select, func
from starlette.datastructures import UploadFile
from starlette.requests import Request
from fastapi import BackgroundTasks

from models import Business, User, Customer, Appointment, Master, GlobalPaymentSettings, PERFORMANCE_INDEXES, ensure_performance_indexes
from routers import auth, dashboard
from utils.auth import AttemptLimiter, normalize_username, save_document
from utils.security import hash_password
from utils.templates import login_html
from ui import get_layout

ROOT = Path(__file__).resolve().parents[1]


def test_auth_page_is_small_and_has_no_remote_assets():
    page = login_html()
    assert len(page.encode()) < 9000
    assert "https://" not in page
    assert 'autocomplete="current-password"' in page
    assert 'action="/login"' in page
    assert 'data-design="radical-v2"' in page
    assert "/static/v2/auth.css" in page
    assert "story-panel" not in page


def test_shell_scripts_run_only_once_and_names_are_escaped():
    user = SimpleNamespace(role="owner", username="<img src=x onerror=alert(1)>",
        business=SimpleNamespace(type="barbershop", lang="ua", name="<script>bad()</script>"))
    page = get_layout("<p>content</p>", user, "dash", "<script>window.onlyOnce=true</script>")
    assert page.count("window.onlyOnce=true") == 1
    assert "<script>bad()</script>" not in page
    assert "&lt;script&gt;bad()" in page
    assert len(page.encode()) < 9000
    assert "<style>" not in page
    assert "/static/vendor/" in page
    assert "https://cdn" not in page
    assert "chart.umd.min.js" not in page
    assert "radical-workspace" in page and "/static/v2/workspace.css" in page
    assert "/static/saas/workspace.css" not in page


def test_root_is_new_marketing_page_not_cached_login():
    async def scenario():
        response=await auth.public_home()
        page=response.body.decode()
        assert response.status_code==200
        assert 'data-design="radical-v2"' in page
        assert "CRM для малого та сервісного бізнесу" in page
        assert 'rel="canonical" href="https://safeorbit.com.pl/"' in page
        assert "https://safeorbit.com.pl/sitemap.xml" in await auth.robots_txt()
        assert b"<loc>https://safeorbit.com.pl/</loc>" in (await auth.sitemap_xml()).body
        assert 'class="hero-v2"' in page
        assert 'id="login-form"' not in page
        assert 'href="/login"' in page and 'href="/register"' in page
    asyncio.run(scenario())


def test_radical_assets_and_font_license_are_local():
    for file in ("brand.svg","core.css","home.css","auth.css","workspace.css","overview.css",
                 "manrope-latin.woff2","manrope-cyrillic.woff2","FONT-LICENSE"):
        assert (ROOT/"static"/"v2"/file).stat().st_size>100


def test_home_shows_checkout_prices_and_first_month_totals():
    from re import findall

    plans = {"plan1": (("setup", 1050), ("monthly", 1150)),
             "plan2": (("setup", 2050), ("monthly", 2150))}
    with patch.object(auth.creem, "PLAN_PRICES", plans):
        page = asyncio.run(auth.public_home()).body.decode()
    prices = findall(r"<td>€([\d.]+)</td>", page)
    assert prices == ["10.50", "20.50", "11.50", "21.50", "22.00", "42.00"]


def test_booking_template_is_discoverable_and_links_a_working_workbook():
    from zipfile import ZipFile

    request = Request({"type": "http", "query_string": b""})
    page = asyncio.run(auth.public_booking_template(request)).body.decode()
    assert f'rel="canonical" href="{auth.PUBLIC_SITE}{auth.BOOKING_TEMPLATE_PAGE}"' in page
    assert '<button id="print-journal"' in page
    path = "static/templates/zhurnal-zapysu-salonu.xlsx"
    assert f'href="/{path}" download' in page
    assert f"<loc>{auth.PUBLIC_SITE}{auth.BOOKING_TEMPLATE_PAGE}</loc>".encode() in asyncio.run(auth.sitemap_xml()).body
    with ZipFile(ROOT / path) as workbook:
        content = workbook.read("xl/worksheets/sheet1.xml")
        assert b"SUMPRODUCT" in content and b"conditionalFormatting" in content


def test_marketing_campaign_survives_demo_and_pricing_before_registration():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from starlette.middleware.sessions import SessionMiddleware

    async def scenario():
        async with api() as (_, sessions):
            app = FastAPI()
            app.add_middleware(SessionMiddleware, secret_key="test-campaign-session")
            app.include_router(auth.router)

            async def isolated_db():
                async with sessions() as db:
                    yield db

            app.dependency_overrides[auth.get_db] = isolated_db
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                original = await client.get("/taryfy")
                assert "utm_source=pricing" in original.text
                landing = await client.get("/crm-dlia-saloniv", params={
                    "utm_source": "linkedin", "utm_medium": "organic_social", "utm_campaign": "salon_workday",
                })
                assert landing.status_code == 200
                with patch.object(auth.demo_workspaces, "start", return_value="demo-session"):
                    demo = await client.get("/login-demo")
                assert demo.headers["location"] == "/admin"
                pricing = await client.get("/taryfy")
                assert "utm_source=pricing" not in pricing.text
                signup = await client.get("/register", params={"plan": "plan2"})
                assert 'name="utm_source" value="linkedin"' in signup.text
                assert 'name="utm_medium" value="organic_social"' in signup.text
                assert 'name="utm_campaign" value="salon_workday"' in signup.text
    asyncio.run(scenario())


def test_theme_switch_is_on_all_surfaces_and_style_is_final_layer():
    user=SimpleNamespace(role="superadmin",username="test",business=None)
    shell=get_layout("sample",user,"super")
    for page in (shell,login_html(),asyncio.run(auth.public_home()).body.decode()):
        assert "data-theme-toggle" in page
        assert page.count('src="/static/v2/theme-init.js') == 1
        assert page.count('src="/static/v2/theme.js') == 1
        assert "/static/v2/theme.css" in page
        assert page.index("/static/v2/theme-init.js") < page.index('rel="stylesheet"')
    head=shell.split("</head>",1)[0]
    assert head.rfind("theme.css") > head.rfind("workspace.css")


def test_theme_tokens_have_wcag_aa_text_contrast():
    import re
    css=(ROOT/"static"/"v2"/"theme.css").read_text()
    def luminance(hexcolor):
        components=[int(hexcolor[i:i+2],16)/255 for i in (1,3,5)]
        linear=[value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4 for value in components]
        return sum(value*weight for value,weight in zip(linear,(.2126,.7152,.0722)))
    def ratio(first,second):
        high,low=sorted((luminance(first),luminance(second)),reverse=True)
        return (high+.05)/(low+.05)
    blocks=re.findall(r'(?:\[data-theme="light"\]|\[data-theme="dark"\])\s*\{([^}]+)\}',css)
    assert len(blocks)>=2
    for block in blocks[:2]:
        tokens=dict(re.findall(r'(--[\w-]+):\s*(#[0-9a-fA-F]{6})',block))
        assert ratio(tokens["--ui-text"],tokens["--ui-surface"])>=4.5
        assert ratio(tokens["--ui-muted"],tokens["--ui-surface"])>=4.5
        assert ratio(tokens["--ui-accent"],tokens["--ui-accent-soft"])>=4.5
    assert 'localStorage.getItem("safeorbit-theme")' in (ROOT/"static"/"v2"/"theme-init.js").read_text()


def test_role_navigation_keeps_retail_links():
    user = SimpleNamespace(role="admin", username="test",
        business=SimpleNamespace(type="retail", lang="ua", name="Retail"))
    assert "API та інтеграції" in get_layout("test", user, "api")
    user.role="superadmin"
    assert "/superadmin" in get_layout("test", user, "super")


def test_every_vendored_dependency_and_license_exists():
    for relative in (
        "bootstrap.min.css", "bootstrap.bundle.min.js", "bootstrap.LICENSE",
        "chart.umd.min.js", "chart.LICENSE", "fullcalendar.min.js", "fullcalendar.LICENSE",
        "sweetalert2.all.min.js", "sweetalert2.LICENSE", "fontawesome/css/all.min.css",
        "fontawesome/LICENSE.txt", "fontawesome/webfonts/fa-solid-900.woff2",
    ):
        assert (ROOT/"static"/"vendor"/relative).stat().st_size > 100


def test_limiter_is_bounded_and_uses_monotonic_window():
    limiter=AttemptLimiter(limit=2,window=60,capacity=3)
    with patch("utils.auth.time.monotonic",return_value=0):
        assert limiter.allow("one") and limiter.allow("one")
        assert not limiter.allow("one")
        for key in ("two","three","four"): limiter.allow(key)
        assert len(limiter.entries)==3
    with patch("utils.auth.time.monotonic",return_value=61):
        assert limiter.allow("four")


def test_username_normalization_does_not_mangle_admin_names():
    assert normalize_username(" +380 (67) 123-45-67 ")=="+380671234567"
    assert normalize_username("  admin ")=="admin"


def test_registration_page_renders_settings_and_escapes_utm():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                db.add(GlobalPaymentSettings(id=1, receiver_name="<script>x</script>",
                    us_swift="TESTSWIFT",is_plan1_active=False,is_plan2_active=True))
                await db.commit()
                request=Request({"type":"http","query_string":b'utm_source=%22%3E%3Cscript%3Ebad%3C%2Fscript%3E'})
                response=await auth.register_page(request,db)
                page=response.body.decode()
                assert response.status_code==200 and "TESTSWIFT" not in page
                assert '<script>x</script>' not in page
                assert '&lt;script&gt;bad&lt;/script&gt;' in page
                assert all(f'name="{field}"' not in page for field in ("receipt", "nda_file", "contract_file"))
                assert 'name="registration_flow" value="access"' in page
                assert 'value="plan1"' not in page
                assert 'value="plan2" checked' in page
    asyncio.run(scenario())


def test_login_normalizes_phone_and_sets_existing_session():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                user=await db.get(User,1);user.username="+380671234567";user.password=hash_password("safe-password")
                await db.commit()
                request=Request({"type":"http","client":("login-test",1),"session":{}})
                response=await auth.login(request," +380 (67) 123-45-67 ","safe-password",db)
                assert response.status_code==303 and response.headers["location"]=="/admin"
                assert request.session=={"user_id":1}
                bad=await auth.login(request,user.username,"incorrect",db)
                assert bad.headers["location"]=="/login?error=invalid"
    asyncio.run(scenario())


def test_dashboard_renders_with_sqlite_and_safe_names():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                user=await db.get(User,1);user.business=await db.get(Business,1)
                customer=await db.get(Customer,1);customer.name="<script>customer</script>"
                today=datetime.now().replace(hour=11,minute=0,second=0,microsecond=0)
                db.add(Appointment(business_id=1,customer_id=1,master_id=1,
                    appointment_time=today,service_type="Hair",cost=150,status="completed"))
                db.add(Appointment(business_id=1,customer_id=1,master_id=1,
                    appointment_time=today+timedelta(days=90),service_type="Future",cost=99000,status="completed"))
                await db.commit()
                page=await dashboard.owner_dash(Request({"type":"http","session":{}}),user,db)
                assert "Ритм вашого бізнесу" in page
                assert "<script>customer</script>" not in page
                assert "overview-chart-data" in page
                assert page.count("let chartsInitialized") == 1
                assert "150" in page and "99 150" not in page
    asyncio.run(scenario())


def test_pending_activation_cannot_leak_business_ids():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                request=Request({"type":"http","session":{}})
                response=await auth.pending_activation_page(2,request,db)
                assert response.status_code==303 and response.headers["location"]=="/login"
                request.session["pending_business_id"]=2
                response=await auth.pending_activation_page(2,request,db)
                assert response.status_code==200 and "Second" in response.body.decode()
    asyncio.run(scenario())


def test_uploads_reject_html_and_ignore_untrusted_filename():
    async def scenario():
        with TemporaryDirectory() as folder:
            with patch("utils.auth.UPLOAD_ROOT",Path(folder)):
                pdf=UploadFile(io.BytesIO(b"%PDF-1.4\nexample"),filename="../../danger.html")
                saved=await save_document(pdf,"documents")
                assert saved.parent==Path(folder)/"documents" and saved.suffix==".pdf"
                bad=UploadFile(io.BytesIO(b"<script>bad</script>"),filename="document.pdf")
                try: await save_document(bad,"documents")
                except ValueError: pass
                else: raise AssertionError("HTML uploaded as a document")
    asyncio.run(scenario())


def test_registration_is_atomic_preserves_promo_and_owns_pending_link():
    async def scenario():
        async with api() as (_,sessions):
            with TemporaryDirectory() as folder:
                with patch("utils.auth.UPLOAD_ROOT", Path(folder) / "static" / "uploads"), patch("routers.auth.ROOT", Path(folder)), patch("routers.auth.notify_registration"), patch("routers.auth.SUPERADMIN_TG_BOT_TOKEN",""), patch("routers.auth.SUPERADMIN_TG_CHAT_ID",""):
                    async with sessions() as db:
                        db.add(GlobalPaymentSettings(id=1,promo_code="TEAM",promo_discount=10))
                        await db.commit()
                        pdf=lambda name: UploadFile(io.BytesIO(b"%PDF-1.4\nsample"),filename=name)
                        request=Request({"type":"http","session":{},"client":("registration-test",1)})
                        response=await auth.register_post(
                            request=request,background_tasks=BackgroundTasks(),name=" New Business ",
                            phone="+380 (67) 555-00-11",password="new-business-password",type="clinic",
                            terms_accepted="yes",plan_type="plan1",applied_promo="team",
                            retail_subcategory=None,payment_country="ua",utm_source=None,utm_medium=None,utm_campaign=None,
                            receipt=pdf("receipt.pdf"),nda_file=pdf("nda.pdf"),contract_file=pdf("contract.pdf"),db=db,
                        )
                        assert response.status_code==303
                        user=await db.scalar(select(User).where(User.username=="+380675550011"))
                        assert user is not None
                        business=await db.get(Business,user.business_id)
                        assert business.name=="New Business" and business.is_active is False
                        assert business.subscription_discount==10
                        assert request.session=={"pending_business_id":business.id}
                        assert len(list(Path(folder).rglob("*.pdf")))==3
    asyncio.run(scenario())


def test_indexes_are_created_and_safe_to_repeat():
    async def scenario():
        async with api() as (_,sessions):
            engine=sessions.kw["bind"]
            async with engine.begin() as connection:
                await connection.run_sync(ensure_performance_indexes)
                await connection.run_sync(ensure_performance_indexes)
                from sqlalchemy import text
                names=(await connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))).scalars().all()
                assert all(index.name in names for index in PERFORMANCE_INDEXES)
    asyncio.run(scenario())


def test_calendar_range_is_bounded_and_keeps_future_months_available():
    async def scenario():
        from routers.admin import get_calendar_data
        async with api() as (_,sessions):
            async with sessions() as db:
                user=await db.get(User,1)
                now=datetime.now()
                future=(now.replace(day=28)+timedelta(days=35)).replace(day=10)
                db.add(Appointment(business_id=1,customer_id=1,appointment_time=future,service_type="Future",cost=300))
                await db.commit()
                start=future.replace(day=1)
                end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
                result=await get_calendar_data(start=start.isoformat(),end=end.isoformat(),user=user,db=db)
                assert {"date":future.strftime("%Y-%m-%d")} in result
                assert await get_calendar_data(start="bad",end="bad",user=user,db=db)==[]
                assert await get_calendar_data(start=start.isoformat(),end=(start+timedelta(days=500)).isoformat(),user=user,db=db)==[]
    asyncio.run(scenario())


def test_workspace_cannot_assign_foreign_master_or_edit_another_master():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                owner=await db.get(User,1)
                assert not await dashboard.valid_assignment(owner,2,db)
                own=await db.get(Master,1);own.can_view_all_appts=False
                specialist=User(username="specialist",password="unused",role="master",business_id=1,master_id=1)
                db.add(specialist)
                other=Appointment(business_id=1,customer_id=1,master_id=None,
                    appointment_time=datetime.now(),service_type="Other",cost=500)
                db.add(other);await db.commit()
                assert not await dashboard.can_manage_appointment(specialist,other,db)
                response=await dashboard.update_appointment(
                    id=other.id,date="2026-11-22",time="10:00",cost="300",master_id="2",
                    delivery_address=None,ttn=None,delivery_status="pending",status="confirmed",
                    user=owner,db=db,
                )
                assert response.headers["location"]=="/admin?error=master"
                assert other.master_id is None
    asyncio.run(scenario())


def test_gzip_and_cache_policy_do_not_cache_tenant_html():
    async def scenario():
        from fastapi import FastAPI
        from starlette.middleware.gzip import GZipMiddleware
        from utils.static import CachedStaticFiles
        import httpx
        app=FastAPI()
        app.add_middleware(GZipMiddleware,minimum_size=1024,compresslevel=4)
        app.mount("/static",CachedStaticFiles(directory=str(ROOT/"static")))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            response=await client.get("/static/saas/auth.css")
            assert response.headers["content-encoding"]=="gzip"
            assert response.headers["cache-control"]=="public, max-age=86400"
            assert response.headers["etag"]
    asyncio.run(scenario())
