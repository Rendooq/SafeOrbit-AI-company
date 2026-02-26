import json
import os
import asyncio
from datetime import datetime, timedelta, time
from typing import List, Optional
import httpx

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, joinedload
from sqlalchemy import select, desc, DateTime, ForeignKey, Text, Integer, and_, Boolean
from groq import AsyncGroq
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:admin@localhost:5432/aicrm")
GREEN_API_ID = os.getenv("GREEN_API_ID", "7103529844")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN", "adb1ee2c22c74279a31fa266126288ec5ebdff6626f141ab81")

client = AsyncGroq(api_key=GROQ_API_KEY)
app = FastAPI(title="AI CRM Pro")
scheduler = AsyncIOScheduler()

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    phone_number: Mapped[str] = mapped_column(Text)
    name: Mapped[Optional[str]] = mapped_column(Text)
    appointments = relationship("Appointment", back_populates="customer")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    appointment_time: Mapped[datetime] = mapped_column(DateTime)
    service_type: Mapped[str] = mapped_column(Text)
    car_brand: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="confirmed")
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    customer = relationship("Customer", back_populates="appointments")

async def get_db():
    async with AsyncSessionLocal() as session: yield session

# ==========================================
# TOOLS (Groq)
# ==========================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Проверяет свободные слоты на дату. Всегда вызывай это ПЕРЕД записью.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"}
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_appointment",
            "description": "Создает запись. Требуй от клиента дату, время, услугу и МАРКУ АВТО.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_time": {"type": "string", "description": "YYYY-MM-DD HH:MM:SS"},
                    "service_type": {"type": "string"},
                    "car_brand": {"type": "string", "description": "Марка и модель автомобиля"}
                },
                "required": ["appointment_time", "service_type", "car_brand"]
            }
        }
    }
]

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
async def get_free_slots(db: AsyncSession, date_str: str) -> List[str]:
    try: target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except: return ["Ошибка формата даты."]
    all_slots = [datetime.combine(target_date, time(hour=h)) for h in range(9, 19)]
    stmt = select(Appointment.appointment_time).where(
        and_(Appointment.appointment_time >= datetime.combine(target_date, time.min),
             Appointment.appointment_time <= datetime.combine(target_date, time.max),
             Appointment.status != 'cancelled')
    )
    result = await db.execute(stmt)
    busy = {dt.replace(second=0, microsecond=0) for dt in result.scalars().all()}
    return [s.strftime("%H:%M") for s in all_slots if s not in busy]

async def send_whatsapp_message(phone: str, message: str):
    url = f"https://7103.api.greenapi.com/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"
    chat_id = f"{phone}@c.us" if not phone.endswith("@c.us") else phone
    async with httpx.AsyncClient() as c:
        try: await c.post(url, json={"chatId": chat_id, "message": message}, timeout=10.0)
        except Exception as e: print(f"WA Error: {e}")

async def check_reminders():
    async with AsyncSessionLocal() as db:
        now = datetime.now()
        target_time = now + timedelta(hours=2)
        stmt = select(Appointment).options(joinedload(Appointment.customer)).where(
            and_(Appointment.appointment_time <= target_time, Appointment.appointment_time > now,
                 Appointment.status == 'confirmed', Appointment.reminder_sent == False)
        )
        result = await db.execute(stmt)
        for appt in result.scalars().all():
            msg = f"⏰ Напоминание! Вы записаны сегодня на {appt.appointment_time.strftime('%H:%M')} ({appt.car_brand}). Ждем вас!"
            await send_whatsapp_message(appt.customer.phone_number, msg)
            appt.reminder_sent = True
            await db.commit()

# ==========================================
# ЧАТ ЛОГИКА
# ==========================================
async def process_chat_logic(db: AsyncSession, business_id: int, phone: str, message_content: str) -> str:
    res = await db.execute(select(Business).where(Business.id == business_id))
    biz = res.scalar_one_or_none()
    if not biz: return "Business not found in DB."
    
    res = await db.execute(select(Customer).where(Customer.phone_number == phone, Customer.business_id == business_id))
    customer = res.scalar_one_or_none()
    if not customer:
        customer = Customer(business_id=business_id, phone_number=phone, name="Client")
        db.add(customer); await db.commit(); await db.refresh(customer)

    db.add(Message(customer_id=customer.id, role="user", content=message_content))
    await db.commit()

    res = await db.execute(select(Message).where(Message.customer_id == customer.id).order_by(desc(Message.created_at)).limit(10))
    history = list(reversed(res.scalars().all()))
    
    system_p = (biz.system_prompt or "") + f"\nToday is {datetime.now().strftime('%Y-%m-%d %H:%M')}. Always ask car brand before booking."
    msgs = [{"role": "system", "content": system_p}]
    for m in history: msgs.append({"role": m.role, "content": m.content})

    chat = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=msgs, tools=tools)
    resp_msg = chat.choices[0].message

    if resp_msg.tool_calls:
        msgs.append(resp_msg)
        for tc in resp_msg.tool_calls:
            args = json.loads(tc.function.arguments)
            res_content = ""
            if tc.function.name == "check_availability":
                slots = await get_free_slots(db, args.get("date"))
                res_content = json.dumps({"available_slots": slots})
            elif tc.function.name == "create_appointment":
                try:
                    appt_dt = datetime.strptime(args.get("appointment_time").replace("T", " "), "%Y-%m-%d %H:%M:%S")
                    new_app = Appointment(business_id=biz.id, customer_id=customer.id, appointment_time=appt_dt, 
                                          service_type=args.get("service_type"), car_brand=args.get("car_brand"))
                    db.add(new_app); await db.commit()
                    res_content = json.dumps({"status": "success", "id": new_app.id})
                except Exception as e: res_content = json.dumps({"status": "error", "message": str(e)})
            
            msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": res_content})
        
        final = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=msgs)
        final_text = final.choices[0].message.content
    else:
        final_text = resp_msg.content

    db.add(Message(customer_id=customer.id, role="assistant", content=final_text))
    await db.commit()
    return final_text

# ==========================================
# ЭНДПОИНТЫ
# ==========================================
@app.post("/whatsapp-webhook")
async def wa_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    if payload.get("typeWebhook") == "incomingMessageReceived":
        try:
            chat_id = payload.get("senderData", {}).get("chatId")
            if not chat_id: return {"status": "no_chat_id"}
            
            phone = chat_id.replace("@c.us", "")
            # Безопасно вытаскиваем текст
            message_data = payload.get("messageData", {})
            text = message_data.get("textMessageData", {}).get("textMessage")
            
            if not text: # Если пришел стикер или картинка - игнорируем, чтобы не упасть
                return {"status": "not_a_text"}

            response = await process_chat_logic(db, 1, phone, text)
            if response: await send_whatsapp_message(phone, response)
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
    return {"status": "ok"}

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(db: AsyncSession = Depends(get_db)):
    stmt = select(Appointment).options(joinedload(Appointment.customer)).order_by(desc(Appointment.appointment_time))
    res = await db.execute(stmt)
    rows = ""
    for a in res.scalars().all():
        rows += f"<tr><td>{a.customer.phone_number}</td><td>{a.appointment_time.strftime('%Y-%m-%d %H:%M')}</td><td>{a.car_brand}</td><td>{a.service_type}</td><td>{a.status}</td></tr>"
    return f"""
    <html><head><meta charset="utf-8"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
    <body class="bg-light"><div class="container py-5"><div class="card shadow-sm"><div class="card-header bg-primary text-white"><h3>🚗 Записи автосервиса</h3></div>
    <div class="card-body"><table class="table table-hover"><thead><tr><th>Телефон</th><th>Время</th><th>Автомобиль</th><th>Услуга</th><th>Статус</th></tr></thead>
    <tbody>{rows}</tbody></table></div></div></div></body></html>
    """

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    scheduler.add_job(check_reminders, 'interval', minutes=10)
    scheduler.start()
