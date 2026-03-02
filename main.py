import json
import io
import os
import hashlib
import pytz
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, joinedload
from sqlalchemy import select, desc, DateTime, ForeignKey, Text, and_, Boolean, func, text, Float
from groq import AsyncGroq
from starlette.middleware.sessions import SessionMiddleware

# ==========================================
# КОНФІГУРАЦІЯ
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aicrm_fmom_user:Wafz1WOdO5fNj3NJGLzSMsht2oFfRM8l@dpg-d6fkpaldi7vc73agq48g-a.frankfurt-postgres.render.com/aicrm_fmom")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
SECRET_KEY = os.getenv("SECRET_KEY", "SUPER_SECRET_KEY_PRO_999")

UA_TZ = pytz.timezone('Europe/Kyiv')
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
client = AsyncGroq(api_key=GROQ_API_KEY)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Helpery безпеки (Password Hashing)
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, stored_password: str) -> bool:
    # Підтримка старих паролів (plain text) та нових (hash)
    if plain_password == stored_password: return True
    return hash_password(plain_password) == stored_password

# ==========================================
# МОДЕЛІ БД
# ==========================================
class Base(DeclarativeBase): pass

class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, default="Ви асистент СТО.")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text) 
    business_id: Mapped[Optional[int]] = mapped_column(ForeignKey("businesses.id"))
    business = relationship("Business")

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    phone_number: Mapped[str] = mapped_column(Text)
    name: Mapped[Optional[str]] = mapped_column(Text)

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    appointment_time: Mapped[datetime] = mapped_column(DateTime)
    service_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="confirmed")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    customer = relationship("Customer")

async def get_db():
    async with AsyncSessionLocal() as session: yield session

# ==========================================
# СИСТЕМНІ ФУНКЦІЇ
# ==========================================
async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    uid = request.session.get("user_id")
    if not uid: return None
    res = await db.execute(select(User).options(joinedload(User.business)).where(User.id == uid))
    return res.scalar_one_or_none()

def get_layout(content: str, user: User, active: str, scripts: str = ""):
    now = datetime.now(UA_TZ).strftime('%H:%M')
    is_super = user.role == "superadmin"
    menu = f"""<a href="/superadmin" class="nav-link {'active' if active=='super' else ''}"><i class="fas fa-user-shield me-2"></i>Адмін</a>""" if is_super else f"""
        <a href="/admin" class="nav-link {'active' if active=='dash' else ''}"><i class="fas fa-chart-line me-2"></i>Панель</a>
        <a href="/admin/klienci" class="nav-link {'active' if active=='kli' else ''}"><i class="fas fa-users me-2"></i>Клієнти</a>
        <a href="/admin/settings" class="nav-link {'active' if active=='set' else ''}"><i class="fas fa-robot me-2"></i>Асистент ШІ</a>"""
    return f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <title>CRM Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{ --primary: #4f46e5; --bg: #f3f4f6; --sidebar: #111827; }}
        body {{ background: var(--bg); font-family: 'Inter', sans-serif; color: #374151; }}
        .sidebar {{ background: var(--sidebar); min-height: 100vh; color: #9ca3af; }}
        .nav-link {{ color: #9ca3af; border-radius: 8px; margin: 4px 0; padding: 10px 15px; transition: all 0.2s; }}
        .nav-link:hover {{ background: rgba(255,255,255,0.05); color: white; }}
        .nav-link.active {{ background: var(--primary); color: white; font-weight: 500; box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.2); }}
        .card {{ border: none; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); background: white; transition: transform 0.2s; }}
        .btn-primary {{ background-color: var(--primary); border: none; padding: 10px 20px; border-radius: 8px; }}
        .btn-primary:hover {{ background-color: #4338ca; }}
        .table thead th {{ font-weight: 600; color: #6b7280; background: #f9fafb; border-bottom: 1px solid #e5e7eb; }}
        h3, h4, h5, h6 {{ font-weight: 600; color: #111827; }}
    </style></head>
    <body><div id="app" class="container-fluid"><div class="row">
        <div class="col-md-2 sidebar p-4 d-none d-md-block">
            <div class="d-flex align-items-center mb-5"><i class="fas fa-bolt text-primary fa-2x me-2"></i><h4 class="m-0 text-white">CRM Pro</h4></div>
            <nav class="nav flex-column gap-1">{menu}</nav>
            <div class="mt-auto pt-5"><a href="/logout" class="nav-link text-danger"><i class="fas fa-sign-out-alt me-2"></i>Вихід</a></div>
        </div>
        <div class="col-md-10 p-4">
            <div class="d-flex justify-content-between align-items-center mb-5">
                <div><h3 class="m-0">Вітаємо, {user.username} 👋</h3><small class="text-muted">Панель керування</small></div>
                <div class="bg-white px-4 py-2 rounded-pill shadow-sm"><i class="far fa-clock me-2 text-primary"></i>{now}</div>
            </div>
            {content}
        </div>
    </div></div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    {scripts}</body></html>"""

# ==========================================
# ПАНЕЛЬ ВЛАСНИКА (ГОЛОВНА З ФОРМОЮ ДОДАВАННЯ)
# ==========================================
@app.get("/admin", response_class=HTMLResponse)
async def owner_dash(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    
    # Статистика
    now = datetime.now(UA_TZ)
    today_start = now.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    # Лічильники
    total = await db.scalar(select(func.count(Appointment.id)).where(Appointment.business_id == user.business_id))
    c_day = await db.scalar(select(func.count(Appointment.id)).where(and_(Appointment.business_id == user.business_id, Appointment.appointment_time >= today_start, Appointment.appointment_time < today_start + timedelta(days=1))))
    c_week = await db.scalar(select(func.count(Appointment.id)).where(and_(Appointment.business_id == user.business_id, Appointment.appointment_time >= week_start)))
    c_month = await db.scalar(select(func.count(Appointment.id)).where(and_(Appointment.business_id == user.business_id, Appointment.appointment_time >= month_start)))

    # Фінанси (Cool Feature)
    rev_month = await db.scalar(select(func.sum(Appointment.cost)).where(and_(Appointment.business_id == user.business_id, Appointment.appointment_time >= month_start))) or 0
    rev_total = await db.scalar(select(func.sum(Appointment.cost)).where(Appointment.business_id == user.business_id)) or 0

    # Статуси
    stmt_status = select(Appointment.status, func.count(Appointment.id)).where(Appointment.business_id == user.business_id).group_by(Appointment.status)
    res_status = await db.execute(stmt_status)
    s_map = {r[0]: r[1] for r in res_status.all()}
    
    stmt = select(Appointment).options(joinedload(Appointment.customer)).where(Appointment.business_id == user.business_id).order_by(desc(Appointment.appointment_time)).limit(10)
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    status_badges = {
        "confirmed": "<span class='badge bg-primary bg-opacity-10 text-primary'>Очікується</span>",
        "completed": "<span class='badge bg-success bg-opacity-10 text-success'>Виконано</span>",
        "cancelled": "<span class='badge bg-danger bg-opacity-10 text-danger'>Скасовано</span>"
    }

    rows = ""
    for a in appts:
        d_str = a.appointment_time.strftime('%Y-%m-%d')
        t_str = a.appointment_time.strftime('%H:%M')
        badge = status_badges.get(a.status, "<span class='badge bg-secondary'>Інше</span>")
        rows += f"""<tr class='align-middle'>
            <td><div class='fw-bold'>{a.customer.name or 'Невідомий'}</div><small class='text-muted'>{a.customer.phone_number}</small></td>
            <td>{d_str} {t_str}</td>
            <td>{a.service_type}</td>
            <td class='fw-bold text-success'>{a.cost:.0f} грн</td>
            <td>{badge}</td>
            <td class='text-end'><button class='btn btn-sm btn-light text-primary' onclick='editApp({a.id}, "{d_str}", "{t_str}", "{a.status}", {a.cost})'><i class='fas fa-edit'></i></button></td>
        </tr>"""

    content = f"""
    <div class="row g-4 mb-4">
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-primary">
            <small class="text-muted fw-bold">ЗАПИСІВ СЬОГОДНІ</small><h3 class="fw-bold m-0">{c_day}</h3></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-info">
            <small class="text-muted fw-bold">ЗАПИСІВ МІСЯЦЬ</small><h3 class="fw-bold m-0">{c_month}</h3></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-success">
            <small class="text-muted fw-bold">КАСА МІСЯЦЬ</small><h3 class="fw-bold m-0 text-success">{rev_month:.0f} ₴</h3></div></div>
        <div class="col-md-3"><div class="card p-3 border-start border-4 border-warning">
            <small class="text-muted fw-bold">КАСА ВСЬОГО</small><h3 class="fw-bold m-0 text-warning">{rev_total:.0f} ₴</h3></div></div>
    </div>
    <div class="row g-4 mb-4">
        <div class="col-md-8"><div class="card p-4 h-100">
            <h5 class="fw-bold mb-4 text-primary">Новий Запис</h5>
            <form action="/admin/add-appointment" method="post" class="row g-3">
                <div class="col-md-6"><label class="small text-muted">Телефон</label><input name="phone" class="form-control bg-light border-0" required></div>
                <div class="col-md-6"><label class="small text-muted">Ім'я</label><input name="name" class="form-control bg-light border-0"></div>
                <div class="col-md-6"><label class="small text-muted">Послуга</label><input name="service" class="form-control bg-light border-0" required></div>
                <div class="col-md-6"><label class="small text-muted">Вартість (грн)</label><input name="cost" type="number" step="0.01" class="form-control bg-light border-0" placeholder="0.00"></div>
                <div class="col-md-4"><label class="small text-muted">Дата</label><input name="date" type="date" class="form-control bg-light border-0" required></div>
                <div class="col-md-4"><label class="small text-muted">Час</label><input name="time" type="time" class="form-control bg-light border-0" required></div>
                <div class="col-md-4 d-flex align-items-end"><button class="btn btn-primary w-100 fw-bold"><i class="fas fa-plus me-2"></i>Додати</button></div>
            </form>
        </div></div>
        <div class="col-md-4"><div class="card p-4 h-100">
            <h5 class="fw-bold mb-3">Статуси</h5>
            <div class="d-flex justify-content-between mb-2"><span>Очікується</span><span class="badge bg-primary rounded-pill">{s_map.get('confirmed', 0)}</span></div>
            <div class="d-flex justify-content-between mb-2"><span>Виконано</span><span class="badge bg-success rounded-pill">{s_map.get('completed', 0)}</span></div>
            <div class="d-flex justify-content-between"><span>Скасовано</span><span class="badge bg-danger rounded-pill">{s_map.get('cancelled', 0)}</span></div>
        </div></div>
    </div>
    <div class="card p-4"><h5 class="mb-4">Останні візити</h5><div class="table-responsive"><table class="table table-hover">
    <thead><tr><th>Клієнт</th><th>Термін</th><th>Послуга</th><th>Сума</th><th>Статус</th><th></th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan=6 class=text-center py-4 text-muted>Немає записів</td></tr>'}</tbody></table></div></div>
    
    <!-- Modal Edit -->
    <div class="modal fade" id="editModal" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered"><div class="modal-content border-0 shadow">
        <div class="modal-header border-0"><h5 class="modal-title fw-bold">Редагування Запису</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
        <form action="/admin/update-appointment" method="post"><div class="modal-body">
            <input type="hidden" name="id" id="editId">
            <div class="mb-3"><label class="small text-muted">Дата</label><input name="date" type="date" id="editDate" class="form-control bg-light border-0" required></div>
            <div class="mb-3"><label class="small text-muted">Час</label><input name="time" type="time" id="editTime" class="form-control bg-light border-0" required></div>
            <div class="mb-3"><label class="small text-muted">Сума (грн)</label><input name="cost" type="number" step="0.01" id="editCost" class="form-control bg-light border-0"></div>
            <div class="mb-3"><label class="small text-muted">Статус</label>
                <select name="status" id="editStatus" class="form-select bg-light border-0">
                    <option value="confirmed">Очікується</option>
                    <option value="completed">Виконано</option>
                    <option value="cancelled">Скасовано</option>
                </select>
            </div>
        </div><div class="modal-footer border-0"><button class="btn btn-primary w-100">Зберегти зміни</button></div></form>
      </div></div>
    </div>"""
    
    scripts = """<script>
    function editApp(id, date, time, status, cost) {
        document.getElementById('editId').value = id;
        document.getElementById('editDate').value = date;
        document.getElementById('editTime').value = time;
        document.getElementById('editStatus').value = status;
        document.getElementById('editCost').value = cost;
        new bootstrap.Modal(document.getElementById('editModal')).show();
    }
    </script>"""
    
    return get_layout(content, user, "dash", scripts)

@app.post("/admin/add-appointment")
async def add_appointment(
    phone: str = Form(...), 
    name: str = Form(None), 
    date: str = Form(...), 
    time: str = Form(...), 
    service: str = Form(...),
    cost: float = Form(0.0),
    user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    if not user: return RedirectResponse("/", status_code=303)

    # 1. Перевіряємо чи є клієнт, якщо немає - створюємо
    stmt = select(Customer).where(and_(Customer.phone_number == phone, Customer.business_id == user.business_id))
    cust = (await db.execute(stmt)).scalar_one_or_none()
    
    if not cust:
        cust = Customer(business_id=user.business_id, phone_number=phone, name=name)
        db.add(cust)
        await db.commit()
        await db.refresh(cust)
    elif name: # Якщо клієнт є, але вказали нове ім'я - оновлюємо
        cust.name = name

    try:
        dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        new_app = Appointment(
            business_id=user.business_id,
            customer_id=cust.id,
            appointment_time=dt,
            service_type=service,
            cost=cost
        )
        db.add(new_app)
        await db.commit()
    except ValueError: pass
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/update-appointment")
async def update_appt(id: int = Form(...), date: str = Form(...), time: str = Form(...), status: str = Form(...), cost: float = Form(0.0), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    res = await db.execute(select(Appointment).where(and_(Appointment.id == id, Appointment.business_id == user.business_id)))
    appt = res.scalar_one_or_none()
    if appt:
        try:
            appt.appointment_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            appt.status = status
            appt.cost = cost
            await db.commit()
        except ValueError: pass
    return RedirectResponse("/admin", status_code=303)

# ==========================================
# РЕШТА ЕНДПОЇНТІВ (ЛОГІН, СУПЕР, СЕТТІНГС)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def login_page():
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Вхід</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
    <style>body { background: #f3f4f6; font-family: 'Inter', sans-serif; height: 100vh; display: flex; align-items: center; justify-content: center; }</style></head>
    <body>
    <div class="card p-5 shadow-lg border-0" style="width: 400px; border-radius: 24px;">
        <div class="text-center mb-4"><h3 class="fw-bold text-dark">Увійти</h3><p class="text-muted">Введіть дані для входу</p></div>
        <form action="/login" method="post">
            <div class="mb-3"><label class="form-label small text-muted">Логін</label><input name="username" class="form-control form-control-lg bg-light border-0" required></div>
            <div class="mb-4"><label class="form-label small text-muted">Пароль</label><input name="password" type="password" class="form-control form-control-lg bg-light border-0" required></div>
            <button class="btn btn-primary w-100 btn-lg fw-bold" style="background: #4f46e5;">Увійти</button>
        </form>
    </div></body></html>"""

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).options(joinedload(User.business)).where(User.username == username))
    user = res.scalar_one_or_none()
    
    if not user: return RedirectResponse("/", status_code=303)
    if not verify_password(password, user.password): return RedirectResponse("/", status_code=303)
    if user.role == "owner" and user.business and not user.business.is_active:
        return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Блокування</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>body { background: #fef2f2; height: 100vh; display: flex; align-items: center; justify-content: center; font-family: sans-serif; }</style></head>
        <body><div class="text-center p-5 bg-white shadow rounded-4" style="max-width: 500px;">
            <div class="mb-4"><span class="fa-stack fa-3x"><i class="fas fa-circle fa-stack-2x text-danger opacity-25"></i><i class="fas fa-lock fa-stack-1x text-danger"></i></span></div>
            <h2 class="fw-bold text-dark mb-3">Акаунт Заблоковано</h2>
            <p class="text-muted mb-4">Доступ до вашого акаунту тимчасово призупинено.<br>Зверніться до адміністратора.</p>
            <a href="/" class="btn btn-outline-danger px-4 rounded-pill">Повернутися</a>
        </div></body></html>""", status_code=403)
    
    request.session["user_id"] = user.id
    return RedirectResponse("/superadmin" if user.role == "superadmin" else "/admin", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)

@app.get("/superadmin", response_class=HTMLResponse)
async def super_admin_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin": return RedirectResponse("/", status_code=303)
    bizs = (await db.execute(select(Business).order_by(Business.id))).scalars().all()
    rows = "".join([f"<tr class='align-middle'><td><span class='text-muted'>#{b.id}</span></td><td class='fw-bold'>{b.name}</td><td><span class='badge {'bg-success' if b.is_active else 'bg-danger'}'>{'АКТИВНИЙ' if b.is_active else 'ЗАБЛОКОВАНИЙ'}</span></td><td class='text-end'><a href='/superadmin/toggle/{b.id}' class='btn btn-sm btn-outline-secondary'><i class='fas fa-power-off'></i> Статус</a></td></tr>" for b in bizs])
    content = f"""<div class='row'><div class='col-md-4'><div class='card p-4 mb-4'><h5 class='fw-bold mb-3'>Додати Нове СТО</h5><form action='/superadmin/add-sto' method='post'><div class='mb-3'><label class='small text-muted'>Назва сервісу</label><input name='name' class='form-control bg-light border-0' required></div><div class='mb-3'><label class='small text-muted'>Логін власника</label><input name='u' class='form-control bg-light border-0' required></div><div class='mb-4'><label class='small text-muted'>Пароль</label><input name='p' class='form-control bg-light border-0' required></div><button class='btn btn-primary w-100'>Створити акаунт</button></form></div></div><div class='col-md-8'><div class='card p-4'><h5 class='fw-bold mb-3'>Список Сервісів</h5><div class='table-responsive'><table class='table table-hover'><thead><tr><th>ID</th><th>Назва</th><th>Статус</th><th class='text-end'>Дія</th></tr></thead><tbody>{rows}</tbody></table></div></div></div></div>"""
    return get_layout(content, user, "super")

@app.post("/superadmin/add-sto")
async def add_sto_fixed(name: str = Form(...), u: str = Form(...), p: str = Form(...), db: AsyncSession = Depends(get_db)):
    nb = Business(name=name, system_prompt="Ви асистент СТО.")
    db.add(nb); await db.commit(); await db.refresh(nb)
    nu = User(username=u, password=hash_password(p), role="owner", business_id=nb.id)
    db.add(nu); await db.commit()
    return RedirectResponse("/superadmin", status_code=303)

@app.get("/superadmin/toggle/{bid}")
async def super_toggle(bid: int, db: AsyncSession = Depends(get_db)):
    b = (await db.execute(select(Business).where(Business.id == bid))).scalar_one_or_none()
    if b: b.is_active = not b.is_active; await db.commit()
    return RedirectResponse("/superadmin", status_code=303)

@app.get("/admin/settings", response_class=HTMLResponse)
async def ai_settings_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    biz = (await db.execute(select(Business).where(Business.id == user.business_id))).scalar_one_or_none()
    content = f"""<div class="card p-4" style="max-width: 800px;">
        <div class="d-flex align-items-center mb-4"><div class="bg-primary bg-opacity-10 p-3 rounded-circle me-3"><i class="fas fa-robot text-primary fa-2x"></i></div><div><h5 class="fw-bold m-0">Налаштування Асистента ШІ</h5><small class="text-muted">Визначте, як ШІ має спілкуватися з клієнтами</small></div></div>
        <form action="/admin/save-prompt" method="post"><label class="form-label fw-bold text-muted">Системна інструкція (Prompt)</label><textarea name="prompt" class="form-control bg-light border-0 p-3 mb-4" rows="10" style="font-family: monospace;">{biz.system_prompt if biz.system_prompt else ""}</textarea><div class="text-end"><button class="btn btn-primary px-4"><i class="fas fa-save me-2"></i>Зберегти зміни</button></div></form></div>"""
    return get_layout(content, user, "set")

@app.post("/admin/save-prompt")
async def save_prompt(prompt: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    biz = (await db.execute(select(Business).where(Business.id == user.business_id))).scalar_one_or_none()
    if biz: biz.system_prompt = prompt; await db.commit()
    return RedirectResponse("/admin/settings", status_code=303)

@app.get("/admin/export-clients")
async def export_clients(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    
    # Експорт історії записів (сума, дата, послуга, ім'я, телефон)
    stmt = select(Appointment).options(joinedload(Appointment.customer)).where(Appointment.business_id == user.business_id).order_by(desc(Appointment.appointment_time))
    res = await db.execute(stmt)
    apps = res.scalars().all()
    
    data = []
    for a in apps:
        data.append({
            "Дата": a.appointment_time.strftime('%Y-%m-%d %H:%M'),
            "Послуга": a.service_type,
            "Сума": a.cost,
            "Ім'я": a.customer.name or "",
            "Телефон": a.customer.phone_number
        })
    
    df = pd.DataFrame(data)
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=clients_export.csv"
    return response

@app.get("/admin/klienci", response_class=HTMLResponse)
async def owner_clients(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    res = await db.execute(select(Customer).where(Customer.business_id == user.business_id))
    custs = res.scalars().all()
    rows = "".join([f"<tr class='align-middle'><td><div class='avatar-circle bg-primary bg-opacity-10 text-primary fw-bold d-inline-flex align-items-center justify-content-center rounded-circle me-3' style='width:40px;height:40px'>{(c.name or '?')[0].upper()}</div>{c.name or 'Без імені'}</td><td>{c.phone_number}</td><td class='text-end'><button class='btn btn-sm btn-light text-primary'><i class='fas fa-edit'></i></button></td></tr>" for c in custs])
    content = f"""<div class="card p-4"><div class="d-flex justify-content-between mb-4"><h5 class="fw-bold">База Клієнтів</h5><a href="/admin/export-clients" class="btn btn-outline-primary btn-sm"><i class="fas fa-download me-2"></i>Експорт</a></div><div class="table-responsive"><table class="table table-hover"><thead><tr><th>Клієнт</th><th>Телефон</th><th class="text-end">Дії</th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return get_layout(content, user, "kli")

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE businesses ADD COLUMN IF NOT EXISTS system_prompt TEXT DEFAULT 'Ви асистент СТО.'"))
        await conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS cost DOUBLE PRECISION DEFAULT 0"))
    async with AsyncSessionLocal() as db:
        if not (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none():
            db.add(User(username="admin", password=hash_password("admin12"), role="superadmin"))
            await db.commit()