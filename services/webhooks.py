import hmac
import hashlib
import json
import asyncio
import logging
from datetime import datetime
import httpx
from sqlalchemy import select
from database import AsyncSessionLocal
from models import WebhookEndpoint, WebhookEventLog
from config import UA_TZ

logger = logging.getLogger(__name__)

async def send_webhook_with_retry(endpoint_id: int, url: str, secret: str, payload_str: str):
    """Відправляє webhook з HMAC SHA256 підписом та Retry логікою (1s, 5s, 15s)."""
    delays = [1, 5, 15]
    
    async with AsyncSessionLocal() as db:
        event_log = WebhookEventLog(
            endpoint_id=endpoint_id,
            event_type=json.loads(payload_str).get("event_type", "unknown"),
            payload=payload_str,
            status="pending"
        )
        db.add(event_log)
        await db.commit()
        await db.refresh(event_log)
        event_id = event_log.id

    async with httpx.AsyncClient() as client:
        for attempt, delay in enumerate(delays, start=1):
            try:
                # Формування HMAC SHA256 підпису
                signature = hmac.new(
                    secret.encode('utf-8'),
                    payload_str.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()
                
                headers = {
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature
                }
                
                resp = await client.post(url, content=payload_str, headers=headers, timeout=10.0)
                resp.raise_for_status()
                
                async with AsyncSessionLocal() as db:
                    ev = await db.get(WebhookEventLog, event_id)
                    if ev:
                        ev.status = "sent"
                        ev.attempts = attempt
                        await db.commit()
                logger.info(f"Webhook sent successfully to {url}")
                return
            except Exception as e:
                logger.warning(f"Webhook attempt {attempt} failed for {url}: {e}")
                async with AsyncSessionLocal() as db:
                    ev = await db.get(WebhookEventLog, event_id)
                    if ev:
                        ev.attempts = attempt
                        ev.last_error = str(e)
                        await db.commit()
                if attempt < len(delays):
                    await asyncio.sleep(delay)
        
        # Failed after all retries
        async with AsyncSessionLocal() as db:
            ev = await db.get(WebhookEventLog, event_id)
            if ev:
                ev.status = "failed"
                await db.commit()
        logger.error(f"Webhook failed for {url} after {len(delays)} attempts")

async def dispatch_webhooks(business_id: int, event_type: str, data: dict):
    """Асинхронний диспатчер, що перевіряє активні ендпоінти та запускає відправку."""
    async with AsyncSessionLocal() as db:
        endpoints = (await db.execute(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.business_id == business_id)
            .where(WebhookEndpoint.is_active == True)
        )).scalars().all()
        
    if not endpoints:
        return
        
    payload = {
        "event_type": event_type,
        "timestamp": datetime.now(UA_TZ).isoformat(),
        "data": data
    }
    payload_str = json.dumps(payload, ensure_ascii=False)
    
    # Fire-and-forget: створюємо незалежні таски для кожного ендпоінта
    for ep in endpoints:
        asyncio.create_task(send_webhook_with_retry(ep.id, ep.url, ep.secret, payload_str))