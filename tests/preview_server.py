"""Local-only visual QA server with synthetic data. Never uses the real .env DB."""
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "preview-not-a-real-key"
os.environ["SECRET_KEY"] = "preview-only-private-session-secret"
os.environ["ENVIRONMENT"] = "test"

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models import Base, Business, User, Customer, Master, Service, Appointment, GlobalPaymentSettings
from database import get_db
from routers import auth, dashboard, admin, superadmin
from utils.static import CachedStaticFiles
from utils.request_security import RequestSecurityMiddleware
from utils.security import hash_password

engine = create_async_engine("sqlite+aiosqlite:///:memory:")
sessions = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(Business(id=1, name="Studio North", is_active=True, type="barbershop"))
        await db.flush()
        db.add(User(id=1, username="preview-owner", password=hash_password("preview-password"), role="owner", business_id=1))
        db.add(User(id=2, username="preview-superadmin", password="not-for-login", role="superadmin"))
        db.add(GlobalPaymentSettings(id=1))
        names = ["Олена Коваль", "Андрій Шевченко", "Марія Бондар", "Владислав Петренко", "Наталія Лисенко", "Дмитро Мельник"]
        for i,name in enumerate(names,1):
            db.add(Customer(id=i, business_id=1, phone_number=f"+380 67 111 22 {i:02d}", name=name))
        for i,name in enumerate(["Анна Мороз", "Олександр Кравчук", "Ірина Савчук"],1):
            db.add(Master(id=i,business_id=1,name=name,role="Стиліст"))
        db.add(Service(id=1,business_id=1,name="Стрижка та укладка",price=850,duration=60))
        await db.flush()
        now=datetime.now().replace(hour=9,minute=0,second=0,microsecond=0)
        for day in range(7):
            for j in range(3):
                db.add(Appointment(business_id=1,customer_id=(day+j)%6+1,master_id=j+1,
                    service_type=["Стрижка та укладка","Фарбування","Догляд за волоссям"][j],
                    appointment_time=now-timedelta(days=day)+timedelta(hours=j),
                    cost=650+day*80+j*150,status="completed" if day>0 else "confirmed"))
        await db.commit()
    yield
    await engine.dispose()

app=FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="preview-only-private-session-secret")
app.add_middleware(GZipMiddleware,minimum_size=1024)
app.add_middleware(RequestSecurityMiddleware)
app.mount("/static",CachedStaticFiles(directory=str(Path(__file__).resolve().parents[1]/"static")),name="static")
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(superadmin.router)

async def isolated_db():
    async with sessions() as db:
        yield db
app.dependency_overrides[get_db]=isolated_db

@app.get("/__preview/workspace")
async def preview_workspace(request: Request):
    request.session["user_id"]=1
    return RedirectResponse("/admin",status_code=303)


@app.get("/__preview/superadmin")
async def preview_superadmin(request: Request):
    request.session["user_id"]=2
    return RedirectResponse("/superadmin",status_code=303)


@app.get("/__preview/mobile", response_class=HTMLResponse)
async def preview_mobile(view: str = "login"):
    paths={"home":"/","login":"/login","register":"/register","workspace":"/__preview/workspace","superadmin":"/__preview/superadmin"}
    path=paths.get(view,"/login")
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>SafeOrbit — 390px responsive QA</title></head><body style="margin:0;background:#e7ede3;display:grid;place-items:center;padding:24px">
    <iframe title="Mobile SafeOrbit preview" src="{path}" style="border:1px solid #d7e0cf;width:390px;height:844px;border-radius:12px;background:white"></iframe>
    </body></html>"""
