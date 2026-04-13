import os
import asyncio
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, Request, Response
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from config import (
    SECRET_KEY,
    GROQ_API_KEY,
    UA_TZ,
)
from database import engine, AsyncSessionLocal, get_db, is_sqlite_db
from models import (
    Base,
    Business,
    User,
    Appointment,
    GlobalPaymentSettings,
)
from dependencies import get_current_user
from routers import auth, dashboard, superadmin, admin, webhooks, widget, api_v1, educational_api
from services.background_tasks import (cart_abandonment_loop,
                                       no_show_protection_loop,
                                       nps_collection_loop, reminder_loop,
                                       rfm_segmentation_loop)
from utils import hash_password
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
if is_sqlite_db():
    logger.info("БД: локальний SQLite (./local.db). Для Render/PostgreSQL задайте змінну оточення DATABASE_URL.")
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY не задано — AI-відповіді та пов’язані функції недоступні. Додайте ключ у .env або змінні оточення.")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=False, same_site="lax")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "upgrade-insecure-requests"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(superadmin.router)
app.include_router(admin.router)
app.include_router(widget.router)
app.include_router(webhooks.router)
app.include_router(api_v1.router)
app.include_router(educational_api.router)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

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
            "ALTER TABLE businesses ADD COLUMN utm_source TEXT;",
            "ALTER TABLE businesses ADD COLUMN utm_medium TEXT;",
            "ALTER TABLE businesses ADD COLUMN utm_campaign TEXT;",
            "ALTER TABLE businesses ADD COLUMN api_key TEXT;"
        ]
        for query in migrations:
            try:
                async with engine.begin() as m_conn:
                    await m_conn.execute(text(query))
            except Exception:
                pass
        
        async with AsyncSessionLocal() as db:
            # Create superadmin if not exists
            if not (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none():
                db.add(User(username="admin", password=hash_password("admin123"), role="superadmin"))
                await db.commit()
            
            # Create demo business and user if not exists
            if not (await db.execute(select(User).where(User.username == "+380999999999"))).scalar_one_or_none():
                demo_biz = Business(name="Демо Бізнес", is_active=True, type="barbershop")
                db.add(demo_biz)
                await db.flush()
                db.add(User(username="+380999999999", password=hash_password("demo123"), role="owner", business_id=demo_biz.id))
                await db.commit()

            # Initialize global payment settings if not exists
            if not (await db.execute(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))).scalar_one_or_none():
                db.add(GlobalPaymentSettings(id=1))
                await db.commit()

        # Start background tasks (from services/background_tasks.py)
        asyncio.create_task(reminder_loop())
        asyncio.create_task(cart_abandonment_loop())
        asyncio.create_task(no_show_protection_loop())
        asyncio.create_task(nps_collection_loop())
        asyncio.create_task(rfm_segmentation_loop())
    except Exception as e:
        logger.error(f"Database startup error: {e}")
        raise

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
