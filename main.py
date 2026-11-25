import os
import asyncio
import secrets
import json
import httpx
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, Request, Response
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from config import (
    SECRET_KEY,
    GROQ_API_KEY,
    UA_TZ,
    IS_PRODUCTION,
    BOOTSTRAP_ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_USERNAME,
)
from database import engine, AsyncSessionLocal, get_db, is_sqlite_db
from models import (
    Base,
    Business,
    User,
    Appointment,
    GlobalPaymentSettings,
    ensure_performance_indexes,
)
from dependencies import get_current_user
from services.demo_workspace import demo_workspaces
from exceptions import APIError
from middleware import LoggingMiddleware, RateLimitMiddleware
from utils.static import CachedStaticFiles
from utils.localization import application_strings
from utils.request_security import RequestSecurityMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from routers import admin, api_v1, auth, creem_events, dashboard, marketplace, superadmin, webhooks, widget, workspace, workspace_tables, api_schools
from services.background_tasks import (cart_abandonment_loop,
                                       no_show_protection_loop,
                                       nps_collection_loop, reminder_loop,
                                       rfm_segmentation_loop)
from utils.security import hash_password
from fastapi.openapi.utils import get_openapi
from ui import get_api_docs_html
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
if is_sqlite_db():
    logger.info("БД: локальний SQLite (./local.db). Для Render/PostgreSQL задайте змінну оточення DATABASE_URL.")
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY не задано — AI-відповіді та пов’язані функції недоступні. Додайте ключ у .env або змінні оточення.")

tags_metadata = [
    {"name": "Auth", "description": "Авторизація API ключів"},
    {"name": "Customers", "description": "Керування клієнтами"},
    {"name": "Appointments", "description": "Керування записами"},
    {"name": "API Keys", "description": "Генерація та відкликання API ключів."},
    {"name": "Webhooks", "description": "Отримання подій у реальному часі."}
]

app = FastAPI(
    title="SafeOrbit API",
    description="""
🚀 Production-ready REST API для інтеграції CRM SafeOrbit.

## Возможности:
- Управление клиентами
- Создание записей (appointments)
- API ключи
- Webhooks

## Аутентификация:
Используйте заголовок:
`X-API-Key: sk_live_...`
""",
    version="1.0.0",
    contact={
        "name": "SafeOrbit Support",
        "email": "support@safeorbit.com",
    },
    openapi_tags=tags_metadata,
)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=IS_PRODUCTION, same_site="lax")
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)
app.add_middleware(RequestSecurityMiddleware)
allowed_hosts = [
    host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,test").split(",") if host.strip()
]
render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_hostname:
    allowed_hosts.append(render_hostname)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# Add custom middlewares
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# Register custom exception handler for APIError
@app.exception_handler(APIError)
async def api_error_exception_handler(request: Request, exc: APIError):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if request.url.path in {"/", "/login", "/register", "/maistry", "/workspace"} or request.url.path.startswith(("/pending-activation/", "/maistry/", "/workspace/", "/proposals/", "/books/")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; media-src 'self'; connect-src 'self'; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'self'"
        )
    elif IS_PRODUCTION:
        response.headers["Content-Security-Policy"] = "upgrade-insecure-requests"
    response.headers["Referrer-Policy"] = "no-referrer" if request.url.path.startswith(("/proposals/", "/books/")) else "strict-origin-when-cross-origin"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response

app.include_router(auth.router, include_in_schema=False)
app.include_router(dashboard.router, include_in_schema=False)
app.include_router(superadmin.router, include_in_schema=False)
app.include_router(admin.router, include_in_schema=False)
app.include_router(widget.router, include_in_schema=False)
app.include_router(workspace.router, include_in_schema=False)
app.include_router(workspace_tables.router, include_in_schema=False)
app.include_router(marketplace.router, include_in_schema=False)
app.include_router(creem_events.router, include_in_schema=False)
app.include_router(webhooks.router, include_in_schema=False)
app.include_router(api_v1.public_chat_router)
app.include_router(api_v1.router)
# School integrations are simulations and must not be sold as working endpoints.

_I18N_TARGETS = {
    "en": "en",
    "ru": "ru",
    "pl": "pl",
    "zh": "zh-CN",
}
_I18N_CACHE: dict[tuple[str, str], str] = {}


async def _translate_ui_text(text_value: str, target_lang: str) -> str:
    cache_key = (target_lang, text_value)
    if cache_key in _I18N_CACHE:
        return _I18N_CACHE[cache_key]

    translated = text_value
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": "auto",
                    "tl": _I18N_TARGETS[target_lang],
                    "dt": "t",
                    "q": text_value,
                },
            )
            response.raise_for_status()
            payload = response.json()
            parts = payload[0] if payload and isinstance(payload[0], list) else []
            translated = "".join(part[0] for part in parts if part and part[0]) or text_value
    except Exception as exc:
        logger.debug("UI translation fallback failed for %s: %s", target_lang, exc)

    _I18N_CACHE[cache_key] = translated
    return translated


@app.post("/api/i18n/translate", include_in_schema=False)
async def translate_ui_text(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return {"translations": {}}

    if not isinstance(payload, dict):
        return {"translations": {}}
    target_lang = str(payload.get("target", "")).lower()
    if target_lang not in _I18N_TARGETS:
        return {"translations": {}}

    raw_texts = payload.get("texts", [])
    if not isinstance(raw_texts, list):
        return {"translations": {}}

    texts: list[str] = []
    seen: set[str] = set()
    allowed = application_strings()
    for item in raw_texts:
        if not isinstance(item, str) or item not in allowed:
            continue
        text_value = " ".join(item.split())
        if not text_value or text_value in seen or len(text_value) > 1000:
            continue
        seen.add(text_value)
        texts.append(text_value)
        if len(texts) >= 80:
            break

    catalog = json.loads((__import__('pathlib').Path(__file__).resolve().parent / 'static/locales/catalog.json').read_text(encoding='utf-8'))
    return {"translations": {text: catalog.get(text, {}).get(target_lang, text) for text in texts}}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        contact=app.contact,
        routes=app.routes,
        tags=app.openapi_tags
    )
    
    paths = openapi_schema.get("paths", {})
    keys_to_remove = [key for key in paths if not key.startswith("/api/v1")]
    for key in keys_to_remove:
        del paths[key]
        
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


@app.get("/api-docs", include_in_schema=False)
async def custom_api_docs():
    return HTMLResponse(content=get_api_docs_html())

# Робимо редирект зі старого /docs на наш новий кастомний (для клієнтів)
@app.get("/docs", include_in_schema=False)
async def redirect_to_custom_docs():
    return RedirectResponse(url="/api-docs")

app.mount("/static", CachedStaticFiles(directory=str(os.path.join(os.path.dirname(__file__), "static"))), name="static")

@app.get("/")
async def root(request: Request):
    if request.session.get("user_id"):
        async with AsyncSessionLocal() as db:
            user = await db.get(User, request.session.get("user_id"))
            if user:
                if user.role == "superadmin":
                    return RedirectResponse("/superadmin")
                return RedirectResponse("/admin")
    return RedirectResponse("/login")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if os.path.exists("static/favicon.ico"):
        return FileResponse("static/favicon.ico")
    if os.path.exists("static/favicon.png"):
        return FileResponse("static/favicon.png")
    return Response(status_code=204)

@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_probe():
    return Response(content="{}", media_type="application/json")


@app.on_event("startup")
async def startup():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            def ensure_appointment_timestamp(connection):
                from sqlalchemy import inspect, text
                columns = {column["name"] for column in inspect(connection).get_columns("appointments")}
                if "created_at" not in columns:
                    connection.execute(text("ALTER TABLE appointments ADD COLUMN created_at TIMESTAMP"))
                    # Unknown historical creation times must not trigger new-record notifications.
                    connection.execute(text("UPDATE appointments SET created_at = :historical WHERE created_at IS NULL"),
                                       {"historical": datetime(1970, 1, 1)})
            await conn.run_sync(ensure_appointment_timestamp)
                
        # Автоматичне додавання нових колонок (кожна у власній транзакції)
        migrations = [
            "ALTER TABLE masters ADD COLUMN working_hours TEXT;",
            "ALTER TABLE customers ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE products ADD COLUMN image_url TEXT;",
            "ALTER TABLE businesses ADD COLUMN transfer_phone_number TEXT;",
            "ALTER TABLE users ADD COLUMN last_updates_view_at TIMESTAMP;",
            "ALTER TABLE global_payment_settings ADD COLUMN plan1_discount INTEGER DEFAULT 0;",
            "ALTER TABLE global_payment_settings ADD COLUMN plan2_discount INTEGER DEFAULT 0;",
            "ALTER TABLE global_payment_settings ADD COLUMN promo_code TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN promo_discount INTEGER DEFAULT 0;",
            "ALTER TABLE global_payment_settings ADD COLUMN promo_target_plan TEXT DEFAULT 'all';",
            "ALTER TABLE global_payment_settings ADD COLUMN promo_expires_at TIMESTAMP;",
            "ALTER TABLE global_payment_settings ADD COLUMN discount_duration_months INTEGER DEFAULT 0;",
            "ALTER TABLE businesses ADD COLUMN subscription_discount INTEGER DEFAULT 0;",
            "ALTER TABLE businesses ADD COLUMN discount_ends_at TIMESTAMP;",
            "ALTER TABLE businesses ADD COLUMN webhook_secret TEXT;", # New field for webhook signature verification
            "ALTER TABLE businesses ADD COLUMN billing_country TEXT DEFAULT 'ua';",
            "ALTER TABLE global_payment_settings ADD COLUMN us_bank_name TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN us_account_number TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN us_routing_number TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN us_swift TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN us_receiver_name TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN us_qr_url TEXT;",
            "ALTER TABLE global_payment_settings ADD COLUMN us_payment_note TEXT;",
            "ALTER TABLE api_keys ADD COLUMN api_key TEXT;",
            "ALTER TABLE api_keys DROP COLUMN IF EXISTS prefix;",
            "ALTER TABLE api_keys DROP COLUMN IF EXISTS key_hash;"
        ]
        for query in migrations:
            try:
                async with engine.begin() as m_conn:
                    await m_conn.execute(text(query))
            except Exception:
                pass
        
        async with AsyncSessionLocal() as db:
            # Create superadmin if not exists
            if BOOTSTRAP_ADMIN_PASSWORD and not (await db.execute(select(User).where(User.username == BOOTSTRAP_ADMIN_USERNAME))).scalar_one_or_none():
                db.add(User(username=BOOTSTRAP_ADMIN_USERNAME, password=hash_password(BOOTSTRAP_ADMIN_PASSWORD), role="superadmin"))
                await db.commit()
            


            # Initialize global payment settings if not exists
            if not (await db.execute(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))).scalar_one_or_none():
                db.add(GlobalPaymentSettings(id=1))
                await db.commit()
            
            # Ensure all existing businesses have a webhook_secret
            businesses_without_secret = (await db.execute(select(Business).where(Business.webhook_secret == None))).scalars().all()
            for biz in businesses_without_secret:
                biz.webhook_secret = secrets.token_hex(32)
                await db.commit()
                await db.refresh(biz)
            
            logger.info("Database startup and migrations complete.")

        # Start background tasks (from services/background_tasks.py)
        async with engine.begin() as connection:
            await connection.run_sync(ensure_performance_indexes)

        app.state.background_tasks = [
            asyncio.create_task(loop())
            for loop in (
                reminder_loop, cart_abandonment_loop, no_show_protection_loop,
                nps_collection_loop, rfm_segmentation_loop,
            )
        ]
        if creem_events.configured():
            app.state.background_tasks.append(asyncio.create_task(creem_events.expire_subscriptions()))
    except Exception as e:
        logger.error(f"Database startup error: {e}")
        raise


@app.on_event("shutdown")
async def shutdown():
    tasks = getattr(app.state, "background_tasks", [])
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    app.state.background_tasks = []
    await demo_workspaces.close()
    await engine.dispose()

@app.get("/api/check-notifications")
async def check_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"type": "none"}
    if user.role == "superadmin":
        count = await db.scalar(select(func.count(Business.id)).where(and_(Business.payment_status == 'pending', Business.parent_id == None)))
        return {"type": "payment_pending", "count": int(count)} if count > 0 else {"type": "none"}
    
    # New appointment check for masters/owners
    # Fetch count of unread or very recent appointments
    now = datetime.now(UA_TZ).replace(tzinfo=None)
    five_mins_ago = now - timedelta(minutes=5)
    
    stmt = select(func.count(Appointment.id)).where(and_(
        Appointment.business_id == user.business_id,
        Appointment.created_at >= five_mins_ago
    ))
    if user.role == "master":
        stmt = stmt.where(Appointment.master_id == user.master_id)
        
    count = await db.scalar(stmt)
    if count > 0:
        return {"type": "new_appointment", "count": int(count)}
        
    return {"type": "none"}
