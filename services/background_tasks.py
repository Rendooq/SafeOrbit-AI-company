import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import UA_TZ
from database import AsyncSessionLocal
from models import (Appointment, AppointmentConfirmation, Business, ChatLog,
                    Customer, CustomerSegment, Master, NPSReview)

logger = logging.getLogger(__name__)


async def reminder_loop():
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            async with AsyncSessionLocal() as db:
                now = datetime.now(UA_TZ).replace(tzinfo=None)
                
                # 1. СТАНДАРТНІ НАГАДУВАННЯ (за 2-3 години до візиту)
                target_time_start = now + timedelta(hours=2)
                target_time_end = now + timedelta(hours=3)
                
                stmt = select(Appointment).options(joinedload(Appointment.customer), joinedload(Appointment.master)).where(and_(
                    Appointment.appointment_time >= target_time_start,
                    Appointment.appointment_time < target_time_end,
                    Appointment.status == 'confirmed',
                    Appointment.reminder_sent == False
                ))
                appts = (await db.execute(stmt)).scalars().all()
                
                for a in appts:
                    biz = await db.get(Business, a.business_id)
                    # TODO: Integrate with a proper SMS sending function if biz.sms_enabled
                    msg = f"Нагадуємо про візит сьогодні о {a.appointment_time.strftime('%H:%M')}. Чекаємо на вас!"
                    
                    if a.customer.telegram_id and biz.telegram_token:
                        async with httpx.AsyncClient() as client:
                            await client.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": a.customer.telegram_id, "text": msg})
                    elif biz.sms_enabled and biz.sms_token:
                        pass 
                    
                    a.reminder_sent = True
                    await db.commit()
                    
                # 2. РОЗУМНИЙ МАРКЕТИНГ: AI-Сеттер для скасованих записів
                stmt_cxl = select(Appointment).options(joinedload(Appointment.customer)).where(and_(
                    Appointment.status == 'cancelled',
                    Appointment.followup_sent == False,
                    Appointment.appointment_time > now - timedelta(days=1)
                ))
                cxls = (await db.execute(stmt_cxl)).scalars().all()
                for cx in cxls:
                    biz = await db.get(Business, cx.business_id)
                    if cx.customer.telegram_id and biz.telegram_token:
                        msg = f"Шкода, що ваш запис на {cx.service_type} скасовано 😔. Можливо, підберемо інший зручний для вас день?"
                        async with httpx.AsyncClient() as client:
                            await client.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": cx.customer.telegram_id, "text": msg})
                    cx.followup_sent = True
                    await db.commit()

                # 3. AI РЕТЕНШН: Реактивація "сплячих" клієнтів (не було візитів > 60 днів)
                # Find customers who haven't had a completed appointment in the last 60 days
                # AND don't have any future appointments
                # AND haven't been sent a reactivation message recently (e.g., in the last 30 days)
                
                sixty_days_ago = now - timedelta(days=60)
                thirty_days_ago = now - timedelta(days=30)

                # Subquery to find customers with recent completed appointments
                recent_customers_subquery = select(Appointment.customer_id).where(
                    and_(
                        Appointment.business_id == Business.id,
                        Appointment.status == 'completed',
                        Appointment.appointment_time >= sixty_days_ago
                    )
                ).subquery()

                # Subquery to find customers with future appointments
                future_customers_subquery = select(Appointment.customer_id).where(
                    and_(
                        Appointment.business_id == Business.id,
                        Appointment.appointment_time > now
                    )
                ).subquery()

                stmt_sleeping = select(Customer, Business).join(Business).where(
                    and_(
                        Customer.business_id == Business.id,
                        Customer.id.notin_(recent_customers_subquery), # No completed appointments in last 60 days
                        Customer.id.notin_(future_customers_subquery), # No future appointments
                        or_(Customer.last_reactivation_sent == None, Customer.last_reactivation_sent < thirty_days_ago) # Not reactivated recently
                    )
                )
                sleeping_clients = (await db.execute(stmt_sleeping)).scalars().all()

                for client, biz in sleeping_clients:
                    if client.telegram_id and biz.telegram_token:
                        # Try to find a master they previously visited, or a random one
                        master_name_for_msg = "вашому майстру"
                        master_id_for_slots = None
                        
                        last_master_appt_id = await db.scalar(select(Appointment.master_id).where(and_(Appointment.customer_id == client.id, Appointment.master_id != None)).order_by(desc(Appointment.appointment_time)).limit(1))
                        if last_master_appt_id:
                            master_record = await db.get(Master, last_master_appt_id)
                            if master_record:
                                master_name_for_msg = master_record.name
                                master_id_for_slots = master_record.id
                        
                        # Suggest a Friday slot, as requested by the user.
                        # This is still a placeholder, as finding *actual* free slots for a specific master
                        # on a specific day (like next Friday) is complex and would require more sophisticated logic
                        # involving working hours, service durations, and existing appointments.
                        suggested_time_str = "час на найближчу п'ятницю" 
                        msg = f"{client.name}, привіт! Давно не бачились у {biz.name}. У нас якраз звільнився {suggested_time_str} до {master_name_for_msg}. Записати?"
                        async with httpx.AsyncClient() as client_tg:
                            await client_tg.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": client.telegram_id, "text": msg})
                        client.last_reactivation_sent = now
                        await db.commit()

        except Exception as e:
            logger.error(f"Reminder Loop Error: {e}")
            await asyncio.sleep(60)


async def cart_abandonment_loop():
    """Smart abandoned cart reminders - 24h follow-up for chats without booking"""
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            async with AsyncSessionLocal() as db:
                now = datetime.now(UA_TZ).replace(tzinfo=None)
                twenty_four_hours_ago = now - timedelta(hours=24)
                
                # Find chats where customer asked about price/service but didn't book
                # (no appointment created in last 24h, and chat has pricing keywords)
                stmt = select(ChatLog, Business).join(Business).where(
                    and_(
                        ChatLog.role == 'user',
                        ChatLog.created_at < twenty_four_hours_ago,
                        ChatLog.created_at > twenty_four_hours_ago - timedelta(hours=1),
                        ChatLog.is_abandoned_cart == False,
                        or_(
                            ChatLog.content.ilike('%ціна%'),
                            ChatLog.content.ilike('%вартість%'),
                            ChatLog.content.ilike('%скільки коштує%'),
                            ChatLog.content.ilike('%price%'),
                            ChatLog.content.ilike('%cost%')
                        )
                    )
                )
                
                abandoned_chats = (await db.execute(stmt)).all()
                
                for chat, biz in abandoned_chats:
                    # Check if customer has any appointment in last 24h
                    has_appointment = await db.scalar(
                        select(Appointment).where(
                            and_(
                                Appointment.business_id == biz.id,
                                Appointment.created_at > twenty_four_hours_ago
                            )
                        ).limit(1)
                    )
                    
                    if not has_appointment and biz.telegram_token:
                        # Send follow-up with discount offer
                        msg = f"👋 Привіт! Ви цікавились нашими послугами. У нас є спеціальна пропозиція: знижка 5% на перший візит! Хочете записатись?"
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                                json={"chat_id": chat.user_identifier, "text": msg}
                            )
                        
                        chat.is_abandoned_cart = True
                        chat.followup_sent_at = now
                        await db.commit()
                        
        except Exception as e:
            logger.error(f"Cart Abandonment Loop Error: {e}")
            await asyncio.sleep(60)


async def no_show_protection_loop():
    """No-show protection - send confirmation 3h before appointment"""
    while True:
        try:
            await asyncio.sleep(600)  # Check every 10 minutes
            async with AsyncSessionLocal() as db:
                now = datetime.now(UA_TZ).replace(tzinfo=None)
                three_hours_later = now + timedelta(hours=3)
                
                # Find appointments in ~3 hours without confirmation sent
                stmt = select(Appointment).options(
                    joinedload(Appointment.customer),
                    joinedload(Appointment.master)
                ).where(
                    and_(
                        Appointment.appointment_time >= three_hours_later - timedelta(minutes=10),
                        Appointment.appointment_time < three_hours_later + timedelta(minutes=10),
                        Appointment.status == 'confirmed'
                    )
                )
                
                upcoming = (await db.execute(stmt)).scalars().all()
                
                for appt in upcoming:
                    # Check if confirmation already sent
                    existing = await db.scalar(
                        select(AppointmentConfirmation).where(
                            AppointmentConfirmation.appointment_id == appt.id
                        )
                    )
                    
                    if not existing:
                        biz = await db.get(Business, appt.business_id)
                        
                        # Create confirmation record
                        confirm = AppointmentConfirmation(
                            appointment_id=appt.id,
                            confirmation_sent_at=now,
                            is_confirmed=False
                        )
                        db.add(confirm)
                        await db.commit()
                        
                        # Send confirmation request
                        if appt.customer.telegram_id and biz.telegram_token:
                            msg = f"⏰ Нагадуємо: у вас запис сьогодні о {appt.appointment_time.strftime('%H:%M')}. \n\nБудь ласка, підтвердіть візит, написавши 'Так' або натисніть кнопку нижче."
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                                    json={
                                        "chat_id": appt.customer.telegram_id,
                                        "text": msg,
                                        "reply_markup": {
                                            "inline_keyboard": [[
                                                {"text": "✅ Підтверджую", "callback_data": f"confirm_{appt.id}"},
                                                {"text": "❌ Скасувати", "callback_data": f"cancel_{appt.id}"}
                                            ]]
                                        }
                                    }
                                )
                        
        except Exception as e:
            logger.error(f"No-Show Protection Loop Error: {e}")
            await asyncio.sleep(60)


async def nps_collection_loop():
    """Automatic NPS/Review collection after appointment"""
    while True:
        try:
            await asyncio.sleep(1800)  # Check every 30 minutes
            async with AsyncSessionLocal() as db:
                now = datetime.now(UA_TZ).replace(tzinfo=None)
                one_hour_ago = now - timedelta(hours=1)
                
                # Find completed appointments from ~1 hour ago without NPS
                stmt = select(Appointment).options(
                    joinedload(Appointment.customer),
                    joinedload(Appointment.master)
                ).where(
                    and_(
                        Appointment.status == 'completed',
                        Appointment.appointment_time <= one_hour_ago,
                        Appointment.appointment_time > one_hour_ago - timedelta(minutes=30)
                    )
                )
                
                completed = (await db.execute(stmt)).scalars().all()
                
                for appt in completed:
                    # Check if NPS already collected
                    existing = await db.scalar(
                        select(NPSReview).where(NPSReview.appointment_id == appt.id)
                    )
                    
                    if not existing and appt.customer.telegram_id:
                        biz = await db.get(Business, appt.business_id)
                        
                        if biz.telegram_token:
                            msg = f"🌟 Як вам візит{' до ' + appt.master.name if appt.master else ''}?\n\nОцініть від 1 до 5:\n1️⃣ - Погано\n5️⃣ - Відмінно!"
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                                    json={
                                        "chat_id": appt.customer.telegram_id,
                                        "text": msg,
                                        "reply_markup": {
                                            "inline_keyboard": [
                                                [{"text": "1", "callback_data": f"nps_{appt.id}_1"},
                                                 {"text": "2", "callback_data": f"nps_{appt.id}_2"},
                                                 {"text": "3", "callback_data": f"nps_{appt.id}_3"},
                                                 {"text": "4", "callback_data": f"nps_{appt.id}_4"},
                                                 {"text": "5", "callback_data": f"nps_{appt.id}_5"}]
                                            ]
                                        }
                                    }
                                )
                        
        except Exception as e:
            logger.error(f"NPS Collection Loop Error: {e}")
            await asyncio.sleep(60)


async def rfm_segmentation_loop():
    """Calculate RFM segmentation for customers daily"""
    while True:
        try:
            await asyncio.sleep(86400)  # Run once per day
            async with AsyncSessionLocal() as db:
                now = datetime.now(UA_TZ).replace(tzinfo=None)
                
                # Get all businesses
                businesses = (await db.execute(select(Business))).scalars().all()
                
                for biz in businesses:
                    customers = (await db.execute(
                        select(Customer).where(Customer.business_id == biz.id)
                    )).scalars().all()
                    
                    for customer in customers:
                        # Calculate RFM metrics
                        appointments = (await db.execute(
                            select(Appointment).where(
                                and_(
                                    Appointment.customer_id == customer.id,
                                    Appointment.status == 'completed'
                                )
                            ).order_by(desc(Appointment.appointment_time))
                        )).scalars().all()
                        
                        total_visits = len(appointments)
                        total_spent = sum(a.cost for a in appointments)
                        
                        days_since_last = 999
                        if appointments:
                            last_visit = appointments[0].appointment_time
                            days_since_last = (now - last_visit).days
                        
                        # Determine segment
                        if total_visits >= 10 and total_spent > 5000:
                            segment = "vip"
                        elif days_since_last > 60:
                            segment = "sleeping"
                        elif total_visits == 0:
                            segment = "new"
                        else:
                            segment = "regular"
                        
                        # Update or create segment
                        existing = await db.scalar(
                            select(CustomerSegment).where(
                                CustomerSegment.customer_id == customer.id
                            )
                        )
                        
                        if existing:
                            existing.rfm_segment = segment
                            existing.total_visits = total_visits
                            existing.total_spent = total_spent
                            existing.days_since_last_visit = days_since_last
                            existing.last_calculated = now
                        else:
                            db.add(CustomerSegment(
                                business_id=biz.id,
                                customer_id=customer.id,
                                rfm_segment=segment,
                                total_visits=total_visits,
                                total_spent=total_spent,
                                days_since_last_visit=days_since_last,
                                last_calculated=now
                            ))
                        
                        await db.commit()
        except Exception as e:
            logger.error(f"RFM Segmentation Loop Error: {e}")
            await asyncio.sleep(3600)
