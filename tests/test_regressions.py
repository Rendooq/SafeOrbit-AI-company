"""Isolated regressions: no real database, mail, AI, or webhook requests."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import os
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch
import subprocess
import sys
from pathlib import Path
from starlette.requests import Request

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "isolated-tests-session-secret"
os.environ["GROQ_API_KEY"] = "isolated-test-key"
os.environ["ENVIRONMENT"] = "test"

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

from database import get_db
from dependencies import get_current_user
from models import Base, ApiKey, Appointment, Business, Customer, IdempotencyKey, Master, User
from routers.api_v1 import router, WEBHOOK_SIGNING_SECRET
from utils.security import hash_password, verify_password


@asynccontextmanager
async def api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([
            Business(id=1, name="First"),
            Business(id=2, name="Second"),
            Business(id=3, name="Disabled", is_active=False),
        ])
        await db.flush()
        db.add_all([
            Customer(id=1, business_id=1, phone_number="111"),
            Customer(id=2, business_id=2, phone_number="222"),
            Master(id=1, business_id=1, name="First master"),
            Master(id=2, business_id=2, name="Second master"),
            ApiKey(business_id=1, api_key="first-key"),
            ApiKey(business_id=2, api_key="second-key"),
            ApiKey(business_id=3, api_key="disabled-key"),
            User(id=1, username="owner", password="unused", role="owner", business_id=1),
        ])
        await db.commit()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="isolated-tests-session-secret")
    app.include_router(router)

    async def isolated_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    try:
        with patch("routers.api_v1.dispatch_webhooks", new=AsyncMock()):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, sessions
    finally:
        await engine.dispose()


def payload(customer=1, master=None):
    return {
        "customer_id": customer,
        "master_id": master,
        "appointment_time": "2026-12-01T10:30:00+02:00",
        "service_type": "Consultation",
    }


def test_idempotent_appointment_replays_serialized_dates():
    async def scenario():
        async with api() as (client, sessions):
            headers = {"X-API-Key": "first-key", "Idempotency-Key": "retry"}
            first = await client.post("/api/v1/appointments", json=payload(), headers=headers)
            assert first.status_code == 201, first.text
            second = await client.post("/api/v1/appointments", json=payload(), headers=headers)
            assert second.status_code == 201, second.text
            assert second.json() == first.json()
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Appointment)) == 1
    asyncio.run(scenario())


def test_idempotency_key_is_tenant_scoped():
    async def scenario():
        async with api() as (client, _):
            for key, customer in [("first-key", 1), ("second-key", 2)]:
                response = await client.post(
                    "/api/v1/appointments", json=payload(customer),
                    headers={"X-API-Key": key, "Idempotency-Key": "same-client-key"},
                )
                assert response.status_code == 201, response.text
                assert response.json()["customer_id"] == customer
    asyncio.run(scenario())


def test_reused_key_with_different_payload_is_conflict():
    async def scenario():
        async with api() as (client, _):
            headers = {"X-API-Key": "first-key", "Idempotency-Key": "retry"}
            assert (await client.post("/api/v1/appointments", json=payload(), headers=headers)).status_code == 201
            changed = dict(payload(), service_type="Different")
            response = await client.post("/api/v1/appointments", json=changed, headers=headers)
            assert response.status_code == 409
    asyncio.run(scenario())


def test_failed_request_does_not_poison_idempotency_key():
    async def scenario():
        async with api() as (client, _):
            headers = {"X-API-Key": "first-key", "Idempotency-Key": "fix-input"}
            bad = await client.post("/api/v1/appointments", json=payload(2), headers=headers)
            assert bad.status_code == 400
            fixed = await client.post("/api/v1/appointments", json=payload(), headers=headers)
            assert fixed.status_code == 201, fixed.text
    asyncio.run(scenario())


def test_expired_key_can_be_reused():
    async def scenario():
        async with api() as (client, sessions):
            headers = {"X-API-Key": "first-key", "Idempotency-Key": "expired"}
            assert (await client.post("/api/v1/appointments", json=payload(), headers=headers)).status_code == 201
            async with sessions() as db:
                record = await db.scalar(select(IdempotencyKey))
                record.expires_at = datetime.utcnow() - timedelta(minutes=1)
                await db.commit()
            changed = dict(payload(), service_type="New request")
            response = await client.post("/api/v1/appointments", json=changed, headers=headers)
            assert response.status_code == 201, response.text
    asyncio.run(scenario())


def test_foreign_master_cannot_be_assigned_on_create():
    async def scenario():
        async with api() as (client, sessions):
            response = await client.post(
                "/api/v1/appointments", json=payload(master=2),
                headers={"X-API-Key": "first-key"},
            )
            assert response.status_code == 400, response.text
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Appointment)) == 0
    asyncio.run(scenario())


def test_foreign_master_cannot_be_assigned_on_update():
    async def scenario():
        async with api() as (client, _):
            headers = {"X-API-Key": "first-key"}
            created = await client.post("/api/v1/appointments", json=payload(master=1), headers=headers)
            assert created.status_code == 201, created.text
            response = await client.put(
                f"/api/v1/appointments/{created.json()['id']}",
                json={"master_id": 2}, headers=headers,
            )
            assert response.status_code == 400, response.text
    asyncio.run(scenario())


def test_disabled_business_key_cannot_read_customers():
    async def scenario():
        async with api() as (client, _):
            response = await client.get("/api/v1/customers", headers={"X-API-Key": "disabled-key"})
            assert response.status_code == 401, response.text
    asyncio.run(scenario())


def test_cross_tenant_customer_is_not_visible():
    async def scenario():
        async with api() as (client, _):
            response = await client.get("/api/v1/customers/2", headers={"X-API-Key": "first-key"})
            assert response.status_code == 404
    asyncio.run(scenario())


def test_foreign_customer_cannot_be_assigned_on_update():
    async def scenario():
        async with api() as (client, _):
            headers = {"X-API-Key": "first-key"}
            created = await client.post("/api/v1/appointments", json=payload(), headers=headers)
            assert created.status_code == 201, created.text
            response = await client.put(
                f"/api/v1/appointments/{created.json()['id']}",
                json={"customer_id": 2}, headers=headers,
            )
            assert response.status_code == 400
    asyncio.run(scenario())


def test_required_appointment_fields_cannot_be_null():
    async def scenario():
        async with api() as (client, _):
            headers = {"X-API-Key": "first-key"}
            created = await client.post("/api/v1/appointments", json=payload(), headers=headers)
            for field in ("appointment_time", "service_type", "status", "cost", "source", "delivery_status"):
                response = await client.put(
                    f"/api/v1/appointments/{created.json()['id']}",
                    json={field: None}, headers=headers,
                )
                assert response.status_code in (400, 422), response.text
    asyncio.run(scenario())


def test_api_health_rejects_missing_and_disabled_credentials():
    async def scenario():
        async with api() as (client, _):
            assert (await client.get("/api/v1/health")).status_code == 401
            assert (await client.get("/api/v1/health", headers={"X-API-Key": "disabled-key"})).status_code == 401
            response = await client.get("/api/v1/health", headers={"X-API-Key": "first-key"})
            assert response.status_code == 200, response.text
            assert response.json()["database"] == "connected"
    asyncio.run(scenario())


def test_incoming_webhook_requires_tenant_credentials():
    async def scenario():
        async with api() as (client, _):
            body = json.dumps({
                "event_type": "appointment.created", "payload": {"id": 1},
                "timestamp": "2026-12-01T10:30:00",
            }).encode()
            assert (await client.post("/api/v1/webhooks/events", content=body)).status_code == 401
            signature = hmac.new(WEBHOOK_SIGNING_SECRET.encode(), body, hashlib.sha256).hexdigest()
            response = await client.post(
                "/api/v1/webhooks/events", content=body,
                headers={"X-API-Key": "first-key", "X-Webhook-Signature": signature},
            )
            assert response.status_code == 200, response.text
    asyncio.run(scenario())


def test_password_long_unicode_round_trip():
    password = "пароль🔐" * 24
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password(password + "!", encoded)


def test_password_legacy_bcrypt_still_supported():
    import bcrypt
    encoded = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode()
    assert verify_password("legacy-password", encoded)
    assert not verify_password("incorrect", encoded)
    assert not verify_password("password", "corrupt-hash")


def test_syntax_checker_is_safe_to_import():
    import test_syntax
    assert callable(test_syntax.main)


def test_application_startup_shutdown_and_public_pages():
    async def idle_loop():
        await asyncio.sleep(3600)

    async def scenario():
        import main
        from contextlib import ExitStack
        async with api() as (unused, sessions):
            test_engine = sessions.kw["bind"]
            with ExitStack() as stack:
                stack.enter_context(patch.object(main, "engine", test_engine))
                stack.enter_context(patch.object(main, "AsyncSessionLocal", sessions))
                stack.enter_context(patch.object(main, "BOOTSTRAP_ADMIN_PASSWORD", ""))
                for name in (
                    "reminder_loop", "cart_abandonment_loop", "no_show_protection_loop",
                    "nps_collection_loop", "rfm_segmentation_loop",
                ):
                    stack.enter_context(patch.object(main, name, idle_loop))
                try:
                    await main.startup()
                    tasks = main.app.state.background_tasks[:]
                    assert len(tasks) == 5
                    async with sessions() as db:
                        assert await db.scalar(select(User).where(User.username == "admin")) is None
                        assert await db.scalar(select(User).where(User.username == "+380999999999")) is None

                    async def isolated_db():
                        async with sessions() as db:
                            yield db

                    main.app.dependency_overrides[get_db] = isolated_db
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
                    ) as client:
                        for url in ("/", "/login", "/static/favicon.png", "/openapi.json"):
                            response = await client.get(url)
                            assert response.status_code == 200, (url, response.status_code)
                            if url == "/":
                                assert 'data-design="radical-v2"' in response.text
                                assert 'class="hero-v2"' in response.text
                            if url == "/login":
                                assert response.headers["cache-control"] == "private, no-store"
                                assert response.headers["content-encoding"] == "gzip"
                                assert "form-action 'self'" in response.headers["content-security-policy"]
                    main.app.dependency_overrides.pop(get_db)
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=main.app), base_url="http://test", follow_redirects=True
                    ) as demo_client, httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=main.app), base_url="http://test", follow_redirects=True
                    ) as other:
                        page = await demo_client.get("/login-demo")
                        assert page.status_code == 200 and "Demo Owner" in page.text
                        assert other.cookies.get("session") is None
                        csrf = demo_client.cookies.get("so_csrf")
                        result = await demo_client.post("/admin/update-customer", data={
                            "id": 1, "name": "Demo isolated edit", "phone": "+12025550101",
                            "notes": "only in one session", "csrf_token": csrf,
                        })
                        assert result.status_code == 200 and "Demo isolated edit" in result.text
                        assert "Demo isolated edit" in (await demo_client.get("/admin/klienci?q=ISOLATED")).text
                        assert (await demo_client.get("/superadmin")).status_code == 403
                        assert (await demo_client.post("/admin/send-sms", headers={"X-CSRF-Token": csrf})).status_code == 403
                        assert "SH-001" in (await demo_client.get("/admin/reports")).text
                        export = await demo_client.get("/admin/reports/export?start=2020-01-01&end=2020-02-01")
                        assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
                        assert (await other.get("/login-demo")).status_code == 200
                        assert "Demo isolated edit" not in (await other.get("/admin/klienci")).text
                        async with sessions() as db:
                            assert await db.scalar(select(User).where(User.username == "Demo Owner")) is None
                finally:
                    main.app.dependency_overrides.clear()
                    await main.shutdown()
                assert all(task.cancelled() for task in tasks)
                assert main.app.state.background_tasks == []
    asyncio.run(scenario())


def test_disabled_business_session_is_cleared():
    async def scenario():
        async with api() as (_, sessions):
            async with sessions() as db:
                business = await db.get(Business, 1)
                business.is_active = False
                await db.commit()
                request = Request({"type": "http", "session": {"user_id": 1}})
                assert await get_current_user(request, db) is None
                assert request.session == {}
    asyncio.run(scenario())


def test_persisted_user_session_works_without_is_active_field():
    async def scenario():
        async with api() as (_, sessions):
            # Fetch from a fresh session: do not attach unmapped test attributes.
            async with sessions() as db:
                request = Request({"type": "http", "session": {"user_id": 1}})
                user = await get_current_user(request, db)
                assert user is not None
                assert user.id == 1
                assert user.business.id == 1
                assert not hasattr(user, "is_active")
                assert request.session == {"user_id": 1}
    asyncio.run(scenario())


def test_application_import_and_static_paths_from_other_cwd():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root))
    result = subprocess.run(
        [sys.executable, "-c",
         "import main; from config import PROJECT_ROOT; "
         "from starlette.routing import Mount; "
         "mount = next(r for r in main.app.routes if isinstance(r, Mount) and r.path == '/static'); "
         "assert str(PROJECT_ROOT / 'static') == mount.app.directory; "
         "print('import-and-paths-ok')"],
        cwd=root / "tests", env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "import-and-paths-ok" in result.stdout


def test_production_requires_private_session_secret():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, ENVIRONMENT="production", SECRET_KEY="SUPER_SECRET_KEY_PRO_999")
    result = subprocess.run(
        [sys.executable, "-c", "import config"], cwd=root, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "private SECRET_KEY" in result.stderr
