import json
import logging
from datetime import datetime
import hmac
import asyncio

import httpx
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import SUPERADMIN_TG_BOT_TOKEN, SUPERADMIN_TG_CHAT_ID
from database import get_db, AsyncSessionLocal
from models import Business, ChatLog, Customer, User, Integration
from services.ai_service import process_ai_request
from config import WEBHOOK_SIGNING_SECRET

router = APIRouter(prefix="/webhook", tags=["Webhooks"])
logger = logging.getLogger(__name__)


async def _process_telegram_update_bg(business_id: int, data: dict, bot_token: str):
    """
    Production-ready: обробка хука у фоновому завданні (Background Task).
    Миттєво звільняє з'єднання з серверами Telegram, уникаючи блокування (Timeout) 
    при 2000+ підключених ботах.
    """
    try:
        # Відкриваємо незалежну сесію до БД для фонового завдання
        async with AsyncSessionLocal() as db:
            # Перевіряємо колбеки (кнопки)
            if "callback_query" in data:
                cb_data = data["callback_query"]["data"]
                chat_id = data["callback_query"]["message"]["chat"]["id"]
                
                if cb_data.startswith("start_reply:"):
                    user_identifier = cb_data.split(":", 1)[1]
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": f"👇 Введіть відповідь для клієнта. ID: {user_identifier}",
                                "reply_markup": {"force_reply": True, "input_field_placeholder": "Ваше повідомлення..."},
                            }
                        )
                async with httpx.AsyncClient() as client:
                    await client.post(f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery", json={"callback_query_id": data["callback_query"]["id"]})
                return

            # Обробка текстових повідомлень
            if "message" in data and "text" in data["message"]:
                chat_id = data["message"]["chat"]["id"]
                user_text = data["message"]["text"]
                
                stmt_cust = select(Customer).where(and_(Customer.telegram_id == str(chat_id), Customer.business_id == business_id))
                cust = (await db.execute(stmt_cust)).scalar_one_or_none()
                
                first_name = data["message"]["from"].get("first_name", "")
                username = data["message"]["from"].get("username", "")
                full_name = f"{first_name} (@{username})" if username else first_name

                if not cust:
                    cust = Customer(business_id=business_id, telegram_id=str(chat_id), name=full_name, phone_number=f"Telegram {chat_id}")
                    db.add(cust)
                    await db.commit()

                # Ручна відповідь менеджера
                if "reply_to_message" in data["message"] and data["message"]["reply_to_message"]["from"]["is_bot"]:
                    replied_text = data["message"]["reply_to_message"]["text"]
                    if replied_text.startswith("👇 Введіть відповідь для клієнта. ID:"):
                        try:
                            user_identifier = replied_text.split("ID: ")[1]
                            target_chat_id = user_identifier.replace("tg_", "")
                            admin_reply_text = user_text
                            
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                    json={"chat_id": target_chat_id, "text": f"📩 <b>Адміністратор:</b>\n{admin_reply_text}", "parse_mode": "HTML"}
                                )
                                await client.post(
                                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                    json={"chat_id": chat_id, "text": f"✅ Відповідь надіслано."}
                                )
                            return
                        except Exception as e:
                            logger.error(f"Error parsing admin reply: {e}")
                            async with httpx.AsyncClient() as client:
                                await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": "❌ Помилка при відправці відповіді."})
                            return

                # Інтелектуальна AI Відповідь
                ai_reply_text, _ = await process_ai_request(business_id, user_text, db, f"tg_{chat_id}", user_name=full_name)
                if ai_reply_text:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": ai_reply_text}
                        )
    except Exception as e:
        logger.error(f"Background Telegram Webhook Error for business {business_id}: {e}")


@router.post("/telegram/{business_id}", include_in_schema=False)
async def telegram_webhook(business_id: int, request: Request, bg_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    try:
        data = await request.json()
        
        # Отримуємо токен ізольовано з таблиці Integrations, а не Business
        stmt = select(Integration).where(and_(
            Integration.business_id == business_id, 
            Integration.provider == 'telegram', 
            Integration.is_active == True
        ))
        integration = (await db.execute(stmt)).scalar_one_or_none()
        
        if not integration or not integration.token:
            return {"ok": False, "error": "Telegram integration not active for this branch"}
            
        # Відправляємо задачу в фон і ВІДРАЗУ повертаємо 200 OK для Telegram
        bg_tasks.add_task(_process_telegram_update_bg, business_id, data, integration.token)
        return {"ok": True}
        
    except Exception as e:
        logger.error(f"Telegram Webhook Error: {e}")
        return {"ok": False}


# TODO: Add webhooks for other integrations (Viber, WhatsApp, etc.)