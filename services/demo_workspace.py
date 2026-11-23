"""Isolated, short-lived copies of the CRM for prospective customers."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from secrets import token_urlsafe
from time import monotonic

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import UA_TZ
from models import Base, Business, User, Customer, Appointment, Master, Service, Product

DEMO_USER_ID = 1
DEMO_SESSION_KEY = "demo_workspace"
DEMO_TTL = 3600
MAX_WORKSPACES = 32

READ_ROUTES = {
    "/admin", "/admin/klienci", "/admin/finance", "/admin/logs", "/admin/calendar-data",
    "/admin/day-details", "/admin/api/calendar-events", "/admin/reports",
    "/admin/reports/export", "/admin/receipt/{id}", "/admin/api/unread-updates", "/api/check-notifications",
}
WRITE_ROUTES = {
    "/admin/add-product", "/admin/delete-product", "/admin/add-appointment", "/admin/update-appointment", "/admin/delete-appointment",
    "/admin/api/update-appointment-time", "/admin/update-customer", "/admin/toggle-client-block",
}


class Workspace:
    def __init__(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.lock = asyncio.Lock()
        self.last_used = monotonic()
        self.users = 0


async def seed(workspace):
    async with workspace.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with workspace.sessions.begin() as db:
        db.add(Business(id=1, name="Studio North • Демо", type="barbershop", is_active=True))
        await db.flush()
        db.add(User(id=DEMO_USER_ID, username="Demo Owner", password="!", role="owner", business_id=1))
        for index, name in enumerate(("Анна Мороз", "Олександр Кравчук"), 1):
            db.add(Master(id=index, business_id=1, name=name, role="Стиліст", is_active=True))
        services = [("Стрижка", 650), ("Укладка", 450), ("Фарбування", 1400)]
        for name, price in services:
            db.add(Service(business_id=1, name=name, price=price, duration=60))
        for index, name in enumerate(("Марія Коваль", "Ірина Савчук", "Андрій Шевченко", "Дмитро Мельник"), 1):
            db.add(Customer(id=index, business_id=1, name=name, phone_number=f"+1202555010{index}"))
        db.add(Product(business_id=1, name="Шампунь для щоденного догляду", sku="SH-001", stock=2, unit_cost=420))
        await db.flush()
        morning = datetime.now(UA_TZ).replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=None)
        for index, offset in enumerate((-5, -3, -2, -1, 0, 0, 1, 3)):
            name, price = services[index % len(services)]
            db.add(Appointment(
                business_id=1, customer_id=index % 4 + 1, master_id=index % 2 + 1,
                appointment_time=morning + timedelta(days=offset, hours=index % 4),
                service_type=name, cost=price, status="completed" if offset < 0 else "confirmed",
            ))


class DemoWorkspaces:
    def __init__(self):
        self.items = {}
        self.lock = asyncio.Lock()

    async def start(self, existing_key):
        async with self.lock:
            now = monotonic()
            for key, workspace in list(self.items.items()):
                if not workspace.users and now - workspace.last_used >= DEMO_TTL:
                    del self.items[key]
                    await workspace.engine.dispose()

            if existing_key in self.items:
                self.items[existing_key].last_used = now
                return existing_key
            if len(self.items) >= MAX_WORKSPACES:
                raise HTTPException(503, "Демо зараз зайняте. Спробуйте трохи пізніше.")

            key = token_urlsafe(32)
            workspace = Workspace()
            try:
                await seed(workspace)
            except BaseException:
                await workspace.engine.dispose()
                raise
            self.items[key] = workspace
            return key

    async def close(self):
        async with self.lock:
            workspaces = list(self.items.values())
            self.items.clear()
        for workspace in workspaces:
            await workspace.engine.dispose()

    @asynccontextmanager
    async def database(self, key, *, touch):
        async with self.lock:
            workspace = self.items.get(key)
            if workspace is None or monotonic() - workspace.last_used >= DEMO_TTL:
                raise HTTPException(410, "Демо завершилося. Відкрийте його знову через /login-demo.")
            workspace.users += 1
            if touch:
                workspace.last_used = monotonic()
        try:
            async with workspace.lock, workspace.sessions() as db:
                yield db
        finally:
            workspace.users -= 1
            if touch:
                workspace.last_used = monotonic()


demo_workspaces = DemoWorkspaces()
