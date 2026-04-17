import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import IdempotencyKey


async def get_idempotency_key(db: AsyncSession, key: str) -> Optional[IdempotencyKey]:
    """Retrieves an idempotency key record."""
    return await db.get(IdempotencyKey, key)


async def create_idempotency_key(
    db: AsyncSession,
    key: str,
    business_id: int,
    request_payload: dict,
    expiration_minutes: int = 1440 # 24 hours
) -> IdempotencyKey:
    """Creates a new idempotency key record."""
    request_hash = hashlib.sha256(json.dumps(request_payload, sort_keys=True).encode('utf-8')).hexdigest()
    expires_at = datetime.now() + timedelta(minutes=expiration_minutes)
    
    idempotency_record = IdempotencyKey(
        idempotency_key=key,
        business_id=business_id,
        request_hash=request_hash,
        expires_at=expires_at
    )
    db.add(idempotency_record)
    await db.commit()
    await db.refresh(idempotency_record)
    return idempotency_record


async def update_idempotency_key(
    db: AsyncSession,
    idempotency_record: IdempotencyKey,
    response_data: dict,
    status_code: int
):
    """Updates an idempotency key record with the response."""
    idempotency_record.response_data = json.dumps(response_data)
    idempotency_record.status_code = status_code
    await db.commit()