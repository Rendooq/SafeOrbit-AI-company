import httpx
import logging
from typing import List
from pydantic import EmailStr
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType

from models import Business, Appointment, Customer, Master
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)

async def send_admin_alert_notification(biz: Business, user_identifier: str, user_question: str, user_name: str = None):
    if not biz.email_notifications_enabled and not biz.telegram_notifications_enabled:
        return

    display_name = user_name if user_name else user_identifier
    subject = f"⚠️ Потрібна допомога: {display_name} кличе адміністратора!"
    
    text_body = f"🚨 Клієнт {display_name} ({user_identifier}) просить допомоги.\n\nПовідомлення: \"{user_question}\""
    html_body = f"""
    <h2>⚠️ Потрібна допомога!</h2>
    <p>Клієнт <strong>{display_name}</strong> (<code>{user_identifier}</code>) просить втручання.</p>
    <p><strong>Повідомлення клієнта:</strong></p>
    <blockquote style="border-left: 4px solid #ccc; padding-left: 1rem; margin-left: 1rem; font-style: italic;">{user_question}</blockquote>
    <p>Будь ласка, зв'яжіться з клієнтом якомога швидше.</p>
    """

    if biz.email_notifications_enabled and biz.notification_email and biz.smtp_server and biz.smtp_username:
        recipients = [e.strip() for e in biz.notification_email.split(',') if e.strip()]
        if not recipients: return
        message = MessageSchema(
            subject=subject,
            recipients=recipients,
            body=html_body,
            subtype=MessageType.html
        )
        
        conf = ConnectionConfig(MAIL_USERNAME=biz.smtp_username, MAIL_PASSWORD=biz.smtp_password, MAIL_FROM=biz.smtp_sender or biz.smtp_username, MAIL_PORT=biz.smtp_port or 587, MAIL_SERVER=biz.smtp_server)
        fm = FastMail(conf)
        try:
            await fm.send_message(message)
            logger.info(f"Admin alert email sent to {biz.notification_email} for business {biz.id}")
        except Exception as e:
            logger.error(f"Failed to send admin alert email for business {biz.id}: {e}")

    if biz.telegram_notifications_enabled and biz.telegram_notification_chat_id and biz.telegram_token:
        chat_ids = [cid.strip() for cid in biz.telegram_notification_chat_id.split(',') if cid.strip()]
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✍️ Відповісти клієнту", "callback_data": f"start_reply:{user_identifier}"}
                ]
            ]
        }
        async with httpx.AsyncClient() as tg_client:
            for chat_id in chat_ids:
                await tg_client.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": chat_id, "text": text_body, "reply_markup": reply_markup})
                logger.info(f"Admin alert telegram sent to {chat_id} for business {biz.id}")

async def send_new_appointment_notifications(biz: Business, appt: Appointment, db: AsyncSession):
    if not biz.email_notifications_enabled and not biz.telegram_notifications_enabled:
        return

    customer = await db.get(Customer, appt.customer_id)
    master = await db.get(Master, appt.master_id) if appt.master_id else None
    
    subject = f"Новий запис: {customer.name} на {appt.appointment_time.strftime('%d.%m %H:%M')}"

    delivery_html_line = f"<p><strong>Адреса доставки:</strong> {appt.delivery_address}</p>" if appt.delivery_address else ""
    html_body = f"""
    <h2>🔥 Нова реєстрація візиту у CRM</h2>
    <p><strong>Профіль гостя:</strong> {customer.name or 'Не вказано'}</p>
    <p><strong>Телефон:</strong> {customer.phone_number}</p>
    <p><strong>Час:</strong> {appt.appointment_time.strftime('%d.%m.%Y %H:%M')}</p>
    <p><strong>Сервіс:</strong> {appt.service_type}</p>
    <p><strong>Сума до сплати:</strong> {appt.cost} грн</p>
    <p><strong>Експерт:</strong> {master.name if master else 'Не вказано'}</p>
        {delivery_html_line}
    """
    delivery_txt_line = f"\nАдреса доставки: {appt.delivery_address}" if appt.delivery_address else ""
    text_body = f"Реєстрація візиту!\nГість: {customer.name or 'Не вказано'}\nТелефон: {customer.phone_number}\nЧас: {appt.appointment_time.strftime('%d.%m.%Y %H:%M')}\nСервіс: {appt.service_type}\nСума до сплати: {appt.cost} грн\nЕксперт: {master.name if master else 'Не вказано'}{delivery_txt_line}"

    if biz.email_notifications_enabled and biz.notification_email and biz.smtp_server and biz.smtp_username:
        recipients = [e.strip() for e in biz.notification_email.split(',') if e.strip()]
        if not recipients: return
        message = MessageSchema(
            subject=subject,
            recipients=recipients,
            body=html_body,
            subtype=MessageType.html
        )
        conf = ConnectionConfig(MAIL_USERNAME=biz.smtp_username, MAIL_PASSWORD=biz.smtp_password, MAIL_FROM=biz.smtp_sender or biz.smtp_username, MAIL_PORT=biz.smtp_port or 587, MAIL_SERVER=biz.smtp_server)
        fm = FastMail(conf)
        try:
            await fm.send_message(message)
            logger.info(f"Email notification sent to {biz.notification_email} for business {biz.id}")
        except Exception as e:
            logger.error(f"Failed to send email notification for business {biz.id}: {e}")

    if biz.telegram_notifications_enabled and biz.telegram_notification_chat_id and biz.telegram_token:
        chat_ids = [cid.strip() for cid in biz.telegram_notification_chat_id.split(',') if cid.strip()]
        async with httpx.AsyncClient() as tg_client:
            for chat_id in chat_ids:
                await tg_client.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": chat_id, "text": text_body})
                logger.info(f"Telegram notification sent to {chat_id} for business {biz.id}")

    if master and master.telegram_chat_id:
        try:
            token = master.personal_bot_token if master.personal_bot_token else biz.telegram_token
            
            if token:
                async with httpx.AsyncClient() as tg_client:
                    master_text = f"👋 Привіт, {master.name}!\nНовий запис до тебе:\n👤 {customer.name}\n📞 {customer.phone_number}\n📅 {appt.appointment_time.strftime('%d.%m %H:%M')}\n✂️ {appt.service_type}{delivery_txt_line}"
                    await tg_client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": master.telegram_chat_id, "text": master_text})
        except Exception as e:
            logger.error(f"Failed to send master notification: {e}")

