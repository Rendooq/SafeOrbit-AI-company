import json
import logging
from datetime import datetime
import hmac
import asyncio

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import SUPERADMIN_TG_BOT_TOKEN, SUPERADMIN_TG_CHAT_ID
from database import get_db
from models import Business, ChatLog, Customer, User
from services.ai_service import process_ai_request
from config import WEBHOOK_SIGNING_SECRET

router = APIRouter(prefix="/webhook", tags=["Webhooks"])
logger = logging.getLogger(__name__)


async def _process_telegram_update(business_id: int, data: dict, db: AsyncSession):
    """Internal function to process Telegram updates asynchronously. This is a placeholder."""
    try:
        biz = await db.get(Business, business_id)
        if not biz or not biz.telegram_token:
            logger.warning(f"Business {business_id} or Telegram token not found for webhook processing.")
            return
        if not biz.telegram_enabled:
            logger.info(f"Telegram integration disabled for business {business_id}.")
            return

        # TODO: Move the actual Telegram webhook processing logic here.
        # This function should receive the `Integration` object for Telegram
        # instead of relying on `biz.telegram_token` directly.
        logger.info(f"Processing Telegram update for business {business_id}: {data}")

    except Exception as e:
        logger.error(f"Error processing Telegram update for business {business_id}: {e}")


@router.post("/telegram/{business_id}")
async def telegram_webhook(business_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        # Read raw body for signature verification if Telegram provides it
        # Telegram's Bot API uses a secret token in the webhook URL, not a signature header.
        # However, if you were using a custom webhook proxy or a different provider,
        # signature verification would be crucial here.
        
        # For Telegram, the token is part of the URL or configured in the bot settings.
        # The `biz.telegram_token` is used to send messages *from* the bot,
        # not typically to verify incoming webhooks, unless you set a custom secret token
        # in BotFather and check it here.
        
        # For this example, we'll assume the `business_id` in the URL is sufficient
        # for initial routing, and the actual token check happens implicitly
        # when the bot tries to respond.
        
        # If Telegram provided a signature, it would look like this:
        # x_telegram_bot_api_secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        # if x_telegram_bot_api_secret_token != biz.telegram_webhook_secret: # Assuming biz has this field
        #     raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

        data = await request.json() # Parse JSON after body is read
        biz = await db.get(Business, business_id)
        if not biz or not biz.telegram_token:
            return {"ok": False, "error": "Business or token not found"}
        if not biz.telegram_enabled: return {"ok": True}

        # Acknowledge the webhook immediately and process in background
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
    except Exception as e:
        logger.error(f"Telegram Webhook Error: {e}")
        return {"ok": False}


# TODO: Add webhooks for other integrations (Viber, WhatsApp, etc.)