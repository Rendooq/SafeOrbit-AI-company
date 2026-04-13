import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import Business, Appointment, Customer, Service

router = APIRouter(prefix="/api/v1", tags=["External API"])
logger = logging.getLogger(__name__)

async def verify_api_key(x_api_key: str = Header(None), db: AsyncSession = Depends(get_db)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Відсутній заголовок X-API-Key")
    
    # Шукаємо бізнес за API ключем
    stmt = select(Business).where(Business.api_key == x_api_key)
    res = await db.execute(stmt)
    biz = res.scalar_one_or_none()
    
    if not biz:
        raise HTTPException(status_code=403, detail="Недійсний API Ключ")
    return biz

@router.get("/appointments")
async def get_appointments(business: Business = Depends(verify_api_key), db: AsyncSession = Depends(get_db)):
    """Отримати список записів"""
    stmt = select(Appointment).where(Appointment.business_id == business.id).order_by(Appointment.appointment_time.desc()).limit(100)
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    return [{
        "id": a.id,
        "date": a.appointment_time.strftime("%Y-%m-%d"),
        "time": a.appointment_time.strftime("%H:%M"),
        "service": a.service_type,
        "cost": a.cost,
        "status": a.status,
        "customer_id": a.customer_id
    } for a in appts]

@router.get("/customers")
async def get_customers(business: Business = Depends(verify_api_key), db: AsyncSession = Depends(get_db)):
    """Отримати список всіх клієнтів"""
    stmt = select(Customer).where(Customer.business_id == business.id).order_by(Customer.id.desc()).limit(100)
    res = await db.execute(stmt)
    customers = res.scalars().all()
    
    return [{
        "id": c.id,
        "name": c.name,
        "phone": c.phone_number,
        "discount_percent": c.discount_percent
    } for c in customers]

@router.get("/services")
async def get_services(business: Business = Depends(verify_api_key), db: AsyncSession = Depends(get_db)):
    """Отримати прайс-лист послуг/товарів"""
    stmt = select(Service).where(Service.business_id == business.id)
    res = await db.execute(stmt)
    services = res.scalars().all()
    
    return [{
        "id": s.id,
        "name": s.name,
        "price": s.price,
        "duration": s.duration
    } for s in services]