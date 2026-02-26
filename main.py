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
DATABASE_URL = os.getenv("DATABASE_URL") # Берется из Environment на Render
GREEN_API_ID = os.getenv("GREEN_API_ID")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")

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
# TOOLS (ВАЖНО: Имена должны совпадать с логикой ниже)
# ==========================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Проверяет свободные часы на дату. Всегда вызывай ПЕРЕД созданием записи.",
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
            "name": "book_appointment",
            "description": "Создает запись в базе. Нужно подтверждение даты, времени, услуги и марки авто.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM"},
                    "service": {"type": "string"},
                    "car_brand": {"type": "string"}
                },
                "required": ["date", "time", "service", "car_brand"]
            }
        }
    }
]

# ==========================================
# ЛОГИКА
# ==========================================
async def get_free_slots(db: AsyncSession, date_str: str) -> List[str]:
    try: target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except: return ["Format error"]
    all_slots = [datetime.combine(target_date, time(hour=h)) for h in range(9, 19)]
    res = await db.execute(select(Appointment.appointment_time).where(
        and_(Appointment.appointment_time >= datetime.combine(target_date, time.min),
             Appointment.appointment_time <= datetime.combine(target_date, time.max))
    ))
    busy = {dt.replace(second=0, microsecond=0) for dt in res.scalars().all()}
    return [s.strftime("%H:%M") for s in all_slots if s not in busy]

async def send_wa(phone: str, text: str):
    url = f"https://7103.api.greenapi.com/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"
    async with httpx.AsyncClient() as c:
        await c.post(url, json={"chatId": f"{phone}@c.us", "message": text})

# ==========================================
# ГЛАВНЫЙ ОБРАБОТЧИК
# ==========================================
async def process_chat(db: AsyncSession, biz_id: int, phone: str, user_text: str):
    # 1. Загрузка данных
    biz = (await db.execute(select(Business).where(Business.id == biz_id))).scalar_one_or_none()
    cust = (await db.execute(select(Customer).where(Customer.phone_number == phone))).scalar_one_or_none()
    if not cust:
        cust = Customer(business_id=biz_id, phone_number=phone, name="Client")
        db.add(cust); await db.commit(); await db.refresh(cust)

    db.add(Message(customer_id=cust.id, role="user", content=user_text))
    await db.commit()

    # 2. История
    hist_res = await db.execute(select(Message).where(Message.customer_id == cust.id).order_by(desc(Message.created_at)).limit(10))
    history = list(reversed(hist_res.scalars().all()))
    
    msgs = [{"role": "system", "content": f"{biz.system_prompt}\nToday: {datetime.now().strftime('%Y-%m-%d %H:%M')}"}]
    for m in history: msgs.append({"role": m.role, "content": m.content})

    # 3. Groq
    chat = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=msgs, tools=tools)
    resp = chat.choices[0].message

    if resp.tool_calls:
        msgs.append(resp)
        for tc in resp.tool_calls:
            args = json.loads(tc.function.arguments)
            if tc.function.name == "check_availability":
                slots = await get_free_slots(db, args['date'])
                res_content = json.dumps({"available": slots})
            elif tc.function.name == "book_appointment":
                dt_str = f"{args['date']} {args['time']}:00"
                new_app = Appointment(business_id=biz_id, customer_id=cust.id, 
                                      appointment_time=datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S"),
                                      service_type=args['service'], car_brand=args['car_brand'])
                db.add(new_app); await db.commit()
                res_content = json.dumps({"status": "success"})
            
            msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.function.name, "content": res_content})
        
        final = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=msgs)
        final_text = final.choices[0].message.content
    else:
        final_text = resp.content

    db.add(Message(customer_id=cust.id, role="assistant", content=final_text))
    await db.commit()
    return final_text

@app.post("/whatsapp-webhook")
async def webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    if payload.get("typeWebhook") == "incomingMessageReceived":
        msg_data = payload.get("messageData", {})
        # Безопасно берем текст, чтобы не падать от стикеров
        text = msg_data.get("textMessageData", {}).get("textMessage")
        if text:
            phone = payload["senderData"]["chatId"].split('@')[0]
            reply = await process_chat(db, 1, phone, text)
            await send_wa(phone, reply)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    scheduler.start()
