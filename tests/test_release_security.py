"""Attack-oriented, isolated regressions. No production data/network calls."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
import json
import socket
import ast
import io

from test_regressions import api
import httpx
from fastapi import FastAPI, Request, Depends, UploadFile
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func
from database import get_db
from models import User, Business, Appointment, Customer, Master, Service, ChatLog, Product
from routers import admin, auth, superadmin, webhooks, widget
from utils.security import hash_password
from utils.request_security import RequestSecurityMiddleware, csrf_token_context
from utils.network import validate_public_url
from utils.static import CachedStaticFiles

ROOT=Path(__file__).resolve().parents[1]


def test_sql_injection_payloads_do_not_change_api_query_scope():
    async def scenario():
        async with api() as (client,sessions):
            headers={"X-API-Key":"first-key"}
            for value in ("' OR 1=1 --", "'; DROP TABLE customers; --", "' UNION SELECT password FROM users --"):
                response=await client.get("/api/v1/customers",params={"search":value},headers=headers)
                assert response.status_code==200
                assert all(row["business_id"]==1 for row in response.json())
                unauthorized=await client.get("/api/v1/customers",headers={"X-API-Key":value})
                assert unauthorized.status_code==401
                path=await client.get("/api/v1/customers/"+value,headers=headers)
                assert path.status_code in (404,422)
            async with sessions() as db:
                assert await db.scalar(select(func.count(Customer.id)))==2
    asyncio.run(scenario())


def test_all_orm_model_attributes_exist():
    import models
    fields={name:set(model.__mapper__.attrs.keys()) for name,model in vars(models).items()
            if isinstance(model,type) and hasattr(model,"__table__")}
    invalid=[]
    for path in [ROOT/"main.py",ROOT/"dependencies.py",*(ROOT/"routers").glob("*.py"),*(ROOT/"services").glob("*.py")]:
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id in fields:
                if node.attr not in fields[node.value.id] and node.attr not in {"__table__","__mapper__"}:
                    invalid.append((path.name,node.lineno,node.value.id,node.attr))
    assert invalid==[]


def test_translation_endpoint_never_transmits_customer_text():
    async def scenario():
        import main
        async def receive():
            return {"type":"http.request","body":json.dumps({"target":"en","texts":["Customer medical history: secret","Бізнес-профілі"]}).encode()}
        request=Request({"type":"http","headers":[],"method":"POST","path":"/api/i18n/translate"},receive)
        with patch("main._translate_ui_text",new=AsyncMock()) as remote:
            result=await main.translate_ui_text(request)
            assert result["translations"]=={"Бізнес-профілі":"Business profiles"}
            remote.assert_not_called()
    asyncio.run(scenario())


def test_csrf_login_native_forms_and_origin_enforcement():
    async def scenario():
        async with api() as (_,sessions):
            app=FastAPI()
            app.add_middleware(SessionMiddleware,secret_key="isolated-session")
            app.add_middleware(RequestSecurityMiddleware)
            app.include_router(auth.router)
            async def isolated():
                async with sessions() as db:yield db
            app.dependency_overrides[get_db]=isolated
            async with sessions() as db:
                user=await db.get(User,1);user.password=hash_password("security-password");await db.commit()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                missing=await client.post("/login",data={"username":"owner","password":"security-password"})
                assert missing.status_code==403
                page=await client.get("/login")
                assert 'name="csrf_token"' in page.text and 'name="csrf-token"' in page.text
                token=client.cookies["so_csrf"]
                evil=await client.post("/login",data={"username":"owner","password":"security-password","csrf_token":token},
                    headers={"Origin":"https://evil.example"})
                assert evil.status_code==403
                response=await client.post("/login",data={"username":"owner","password":"security-password","csrf_token":token})
                assert response.status_code==303 and response.headers["location"]=="/admin"
                payload=await client.post("/login",data={"username":"' OR 1=1 --","password":"security-password","csrf_token":token})
                assert payload.status_code==303 and "error=invalid" in payload.headers["location"]
    asyncio.run(scenario())


def test_request_body_limit_and_forged_session():
    async def scenario():
        app=FastAPI()
        app.add_middleware(SessionMiddleware,secret_key="isolated-session")
        app.add_middleware(RequestSecurityMiddleware)
        @app.post("/api/test")
        async def probe(request:Request):
            return {"size":len(await request.body()),"session":request.session}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            response=await client.post("/api/test",content=b"x"*(1024*1024+1))
            assert response.status_code==413
            client.cookies.set("session","forged-owner")
            forged=await client.post("/api/test",content=b"ok")
            assert forged.status_code==403
    asyncio.run(scenario())


def test_private_documents_require_matching_tenant_session():
    async def scenario():
        async with api() as (_,sessions):
            with TemporaryDirectory() as directory:
                folder=Path(directory)/"uploads"/"documents";folder.mkdir(parents=True)
                (folder/"test.pdf").write_bytes(b"%PDF-1.4")
                async with sessions() as db:
                    business=await db.get(Business,1);business.contract_url="/static/uploads/documents/test.pdf";await db.commit()
                app=FastAPI()
                app.add_middleware(SessionMiddleware,secret_key="isolated")
                @app.get("/session/{bid}")
                async def session(bid:int,request:Request):
                    request.session["pending_business_id"]=bid
                    return {"ok":True}
                app.mount("/static",CachedStaticFiles(directory=directory))
                with patch("utils.static.AsyncSessionLocal",sessions):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                        assert (await client.get("/static/uploads/documents/test.pdf")).status_code==404
                        await client.get("/session/2")
                        assert (await client.get("/static/uploads/documents/test.pdf")).status_code==404
                        await client.get("/session/1")
                        result=await client.get("/static/uploads/documents/test.pdf")
                        assert result.status_code==200
                        assert result.headers["cache-control"]=="private, no-store"
                        assert (await client.get("/static/../../.env")).status_code==404
    asyncio.run(scenario())


def test_ssrf_rejects_non_https_credentials_private_and_mixed_dns():
    async def scenario():
        async def check(url,ip):
            response=[(socket.AF_INET,socket.SOCK_STREAM,6,"",(ip,443))]
            with patch("utils.network.socket.getaddrinfo",return_value=response):
                try:await validate_public_url(url)
                except ValueError:return
                raise AssertionError("Unsafe URL accepted: "+url)
        for url in ("http://example.com","https://user:pass@example.com","https://example.com:22","https://example.com/#token"):
            await check(url,"8.8.8.8")
        for ip in ("127.0.0.1","10.1.1.1","169.254.169.254","192.168.1.1","0.0.0.0"):
            await check("https://example.com",ip)
        with patch("utils.network.socket.getaddrinfo",return_value=[
            (socket.AF_INET,socket.SOCK_STREAM,6,"",("8.8.8.8",443)),
            (socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",443))]):
            try:await validate_public_url("https://example.com")
            except ValueError:pass
            else:raise AssertionError("Mixed DNS accepted")
    asyncio.run(scenario())


def test_webhook_create_rejects_metadata_target():
    async def scenario():
        async with api() as (client,_):
            response=await client.post("/api/v1/webhooks",headers={"X-API-Key":"first-key"},
                json={"url":"http://169.254.169.254/latest/meta-data","events":["appointment.created"]})
            assert response.status_code in (400,422)
    asyncio.run(scenario())


def test_telegram_unsigned_update_has_no_effect():
    async def scenario():
        async with api() as (_,sessions):
            app=FastAPI();app.include_router(webhooks.router)
            async def isolated():
                async with sessions() as db:yield db
            app.dependency_overrides[get_db]=isolated
            with patch("routers.webhooks._process_telegram_update_bg",new=AsyncMock()) as process:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                    response=await client.post("/webhook/telegram/1",json={"message":{"text":"forged"}})
                    assert response.status_code==401
                    process.assert_not_called()
    asyncio.run(scenario())


def test_public_booking_rejects_foreign_master_without_creating_customer():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                response=await widget.process_public_booking(business_id=1,phone="+38012345678",name="Guest",
                    date="2026-12-01",time="10:00",service="Service",master_id="2",delivery_address=None,db=db)
                assert response.status_code==400
                assert await db.scalar(select(func.count(Customer.id)))==2
    asyncio.run(scenario())


def test_state_changing_superadmin_routes_are_post_only():
    import main
    protected = [route for route in superadmin.router.routes
                 if route.path.startswith(("/superadmin/toggle", "/superadmin/delete/", "/superadmin/delete-payment/"))]
    assert protected
    assert all("GET" not in route.methods for route in protected)
    assert not any(getattr(route,"path","").startswith("/api/schools") for route in main.app.routes)


def test_translation_catalog_complete_entries_and_no_remote_user_translation():
    catalog=json.loads((ROOT/"static/locales/catalog.json").read_text(encoding="utf-8"))
    assert len(catalog) >= 900
    bundled = (ROOT/"static/locales/catalog.js").read_text(encoding="utf-8").strip()
    assert json.loads(bundled.removeprefix("window.SafeOrbitLocaleCatalog = ").removesuffix(";")) == catalog
    for phrase in ("Бізнес-профілі","З поверненням","Ваш день.","Створити запис","Зберегти зміни","Реквізити для оплати","Звіт за записами","Спробувати демо без пароля","Блокування клієнта"):
        assert set(catalog[phrase])=={"en","ru","pl","zh"}
        assert all(catalog[phrase].values())
    source=(ROOT/"static/i18n.js").read_text(encoding="utf-8")
    assert "const MACHINE_TRANSLATION_ENABLED = false" in source
    assert "window.SafeOrbitLocaleCatalog" in source
    assert "safeorbitRenderedText" in source


def test_main_rejects_untrusted_host():
    async def scenario():
        import main
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://evil.example") as client:
            assert (await client.get("/login")).status_code==400
    asyncio.run(scenario())


def test_cookie_api_request_requires_csrf_header():
    async def scenario():
        app=FastAPI();app.add_middleware(SessionMiddleware,secret_key="test");app.add_middleware(RequestSecurityMiddleware)
        @app.get("/start")
        async def start(request:Request):
            request.session["user_id"]=1
            from fastapi.responses import HTMLResponse
            from utils.templates import render_template
            return HTMLResponse(render_template("auth/login.html"))
        @app.post("/change")
        async def change():return {"ok":True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            await client.get("/start")
            assert (await client.post("/change",json={"id":1})).status_code==403
            assert (await client.post("/change",json={"id":1},headers={"X-CSRF-Token":client.cookies["so_csrf"]})).status_code==200
    asyncio.run(scenario())


def test_widget_foreign_service_rejected_without_side_effects():
    async def scenario():
        async with api() as (_,sessions):
            async with sessions() as db:
                service=Service(business_id=2,name="Foreign",price=100,duration=30)
                db.add(service);await db.commit()
                result=await widget.widget_book_api({"business_id":1,"service_id":service.id,"phone":"12345",
                    "name":"New customer","date":"2026-12-10T10:00:00"},db)
                assert result["success"] is False
                assert await db.scalar(select(func.count(Customer.id)))==2
    asyncio.run(scenario())


def test_api_rejects_negative_and_nonfinite_cost():
    async def scenario():
        async with api() as (client,_):
            for cost in (-1,"NaN","Infinity"):
                response=await client.post("/api/v1/appointments",headers={"X-API-Key":"first-key"},
                    json={"customer_id":1,"appointment_time":"2026-12-10T10:00:00","service_type":"Test","cost":cost})
                assert response.status_code==422
    asyncio.run(scenario())

def test_chat_reply_requires_a_conversation_in_the_same_business():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                db.add_all([
                    ChatLog(business_id=1, user_identifier="web_own", role="user", content="Hello"),
                    ChatLog(business_id=2, user_identifier="web_other", role="user", content="Hello"),
                ])
                await db.commit()
                owner = await db.get(User, 1)
                denied = await admin.api_chat_send("web_other", "Not allowed", owner, db)
                assert denied == {"success": False}
                accepted = await admin.api_chat_send("web_own", "Hello back", owner, db)
                assert accepted == {"success": True}
                assert await db.scalar(select(func.count(ChatLog.id)).where(ChatLog.business_id == 2)) == 1
    asyncio.run(scenario())


def test_inventory_photo_uses_file_content_not_client_filename():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                owner = await db.get(User, 1)
                with TemporaryDirectory() as directory, patch.object(admin, "ROOT", Path(directory)):
                    upload = UploadFile(io.BytesIO(b"plain text"), filename="product.png")
                    denied = await admin.add_product("Product", "SKU", 10, [], [], [], upload, owner, db)
                    assert denied.headers["location"] == "/admin/finance?error=image"
                    assert await db.scalar(select(func.count(Product.id))) == 0
                    assert not (Path(directory) / "static").exists()
    asyncio.run(scenario())

def test_widget_booking_checks_existing_service_duration():
    from datetime import datetime, timedelta
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                visit = (datetime.now() + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
                service = Service(business_id=1, name="Consultation", duration=60, price=25)
                db.add_all([service, Appointment(
                    business_id=1, customer_id=1, master_id=1,
                    appointment_time=visit, service_type="Consultation",
                )])
                await db.commit()
                result = await widget.widget_book_api({
                    "business_id": 1, "service_id": service.id, "phone": "111",
                    "date": visit.date().isoformat(), "time": "10:30",
                }, db)
                assert not result["success"] and "зайнятий" in result["error"]
                assert await db.scalar(select(func.count(Appointment.id))) == 1
    asyncio.run(scenario())
