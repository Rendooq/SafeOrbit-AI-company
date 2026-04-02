import json
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import SUPERADMIN_TG_BOT_TOKEN, SUPERADMIN_TG_CHAT_ID
from database import get_db
from models import Business, ChatLog, Customer, User
from services.ai_service import process_ai_request

router = APIRouter(prefix="/webhook", tags=["Webhooks"])
logger = logging.getLogger(__name__)


@router.post("/telegram/{business_id}")
async def telegram_webhook(business_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        data = await request.json()
        biz = await db.get(Business, business_id)
        if not biz or not biz.telegram_token:
            return {"ok": False, "error": "Business or token not found"}
        if not biz.telegram_enabled: return {"ok": True}

        if "callback_query" in data:
            cb_data = data["callback_query"]["data"]
            chat_id = data["callback_query"]["message"]["chat"]["id"]
            
            if cb_data.startswith("start_reply:"):
                user_identifier = cb_data.split(":", 1)[1]
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": f"👇 Введіть відповідь для клієнта. ID: {user_identifier}",
                            "reply_markup": {"force_reply": True, "input_field_placeholder": "Ваше повідомлення..."},
                        }
                    )
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{biz.telegram_token}/answerCallbackQuery", json={"callback_query_id": data["callback_query"]["id"]})
            return {"ok": True}

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
                db.add(cust); await db.commit()

            if "reply_to_message" in data["message"] and data["message"]["reply_to_message"]["from"]["is_bot"]:
                replied_text = data["message"]["reply_to_message"]["text"]
                if replied_text.startswith("👇 Введіть відповідь для клієнта. ID:"):
                    try:
                        user_identifier = replied_text.split("ID: ")[1]
                        target_chat_id = user_identifier.replace("tg_", "")
                        admin_reply_text = user_text
                        
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                                json={"chat_id": target_chat_id, "text": f"📩 <b>Адміністратор:</b>\n{admin_reply_text}", "parse_mode": "HTML"}
                            )
                            await client.post(
                                f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                                json={"chat_id": chat_id, "text": f"✅ Відповідь надіслано."}
                            )
                        return {"ok": True}
                    except Exception as e:
                        logger.error(f"Error parsing admin reply: {e}")
                        async with httpx.AsyncClient() as client:
                            await client.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": chat_id, "text": "❌ Помилка при відправці відповіді."})
                        return {"ok": True}

            ai_reply_text, _ = await process_ai_request(business_id, user_text, db, f"tg_{chat_id}", user_name=full_name)
            if ai_reply_text:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                        json={"chat_id": chat_id, "text": ai_reply_text}
                    )
        return {"ok": True}
    except Exception as e:
        logger.error(f"Telegram Webhook Error: {e}")
        return {"ok": False}


# TODO: Add webhooks for other integrations (Viber, WhatsApp, etc.)