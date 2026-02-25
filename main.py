import json
import os
from datetime import datetime
from typing import List, Optional
import httpx

from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import select, desc, DateTime, ForeignKey, Text, Integer
from groq import AsyncGroq

# ==========================================
# КОНФИГУРАЦИЯ (Рекомендуется вынести в Environment Variables на Render)
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:admin@localhost:5432/aicrm")
GREEN_API_ID = os.getenv("GREEN_API_ID", "7103529844")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN", "adb1ee2c22c74279a31fa266126288ec5ebdff6626f141ab81")

client = AsyncGroq(api_key=GROQ_API_KEY)
app = FastAPI(title="AI CRM Integrator")

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

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

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    appointment_time: Mapped[datetime] = mapped_column(DateTime)
    service_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="confirmed")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# ==========================================
# SCHEMAS
# ==========================================
class WebhookRequest(BaseModel):
    business_id: int
    phone: str
    message: str

tools = [{
    "type": "function",
    "function": {
        "name": "create_appointment",
        "description": "Записывает клиента на услугу на конкретную дату и время.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_time": {"type": "string", "description": "YYYY-MM-DD HH:MM:SS"},
                "service_type": {"type": "string"}
            },
            "required": ["appointment_time", "service_type"]
        }
    }
}]

# ==========================================
# ОСНОВНАЯ ЛОГИКА
# ==========================================
async def process_chat_logic(db: AsyncSession, business_id: int, phone: str, message_content: str) -> str:
    res = await db.execute(select(Business).where(Business.id == business_id))
    business = res.scalar_one_or_none()
    if not business: raise HTTPException(404, "Business not found")

    res = await db.execute(select(Customer).where(Customer.phone_number == phone, Customer.business_id == business_id))
    customer = res.scalar_one_or_none()
    if not customer:
        customer = Customer(business_id=business_id, phone_number=phone, name="Client")
        db.add(customer); await db.commit(); await db.refresh(customer)

    db.add(Message(customer_id=customer.id, role="user", content=message_content))
    await db.commit()

    res = await db.execute(select(Message).where(Message.customer_id == customer.id).order_by(desc(Message.created_at)).limit(5))
    history = list(reversed(res.scalars().all()))
    
    msgs = [{"role": "system", "content": business.system_prompt or "You are a helpful assistant."}]
    for m in history: msgs.append({"role": m.role, "content": m.content})

    chat = await client.chat.completions.create(
        model="llama-3.3-70b-versatile", messages=msgs, tools=tools, tool_choice="auto"
    )
    
    resp_msg = chat.choices[0].message
    final_text = resp_msg.content

    if resp_msg.tool_calls:
        msgs.append(resp_msg)
        for tc in resp_msg.tool_calls:
            args = json.loads(tc.function.arguments)
            new_app = Appointment(
                business_id=business.id,
                customer_id=customer.id,
                appointment_time=datetime.strptime(args['appointment_time'].replace("T", " "), "%Y-%m-%d %H:%M:%S"),
                service_type=args['service_type']
            )
            db.add(new_app); await db.commit()
            
            msgs.append({
                "role": "tool", "tool_call_id": tc.id, "name": "create_appointment",
                "content": json.dumps({"status": "success", "id": new_app.id})
            })
        
        second_chat = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=msgs)
        final_text = second_chat.choices[0].message.content

    if final_text:
        db.add(Message(customer_id=customer.id, role="assistant", content=final_text))
        await db.commit()
    
    return final_text

# ==========================================
# ЭНДПОИНТЫ
# ==========================================

@app.post("/webhook")
async def webhook_handler(req: WebhookRequest, db: AsyncSession = Depends(get_db)):
    try:
        response_text = await process_chat_logic(db, req.business_id, req.phone, req.message)
        return {"response": response_text}
    except Exception as e:
        print(f"ERROR Webhook: {e}")
        return {"error": str(e)}

@app.post("/whatsapp-webhook")
async def whatsapp_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    try:
        if payload.get("typeWebhook") == "incomingMessageReceived":
            sender_data = payload.get("senderData", {})
            chat_id = sender_data.get("chatId")
            message_data = payload.get("messageData", {})
            text_message = message_data.get("textMessageData", {}).get("textMessage")

            if chat_id and text_message:
                phone = chat_id.replace("@c.us", "")
                # Принудительно используем business_id=1 для тестов WhatsApp
                response_text = await process_chat_logic(db, 1, phone, text_message)

                if response_text:
                    # Используем корректный URL Green-API (7103 уже в ID_INSTANCE)
                    url = f"https://7103.api.greenapi.com/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"
                    async with httpx.AsyncClient() as httpx_client:
                        await httpx_client.post(url, json={
                            "chatId": chat_id,
                            "message": response_text
                        })
        return {"status": "ok"}
    except Exception as e:
        print(f"ERROR WhatsApp: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)