import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import IdempotencyKey


async def get_idempotency_key(db: AsyncSession, key: str) -> Optional[IdempotencyKey]:
    """Retrieves an idempotency key record."""
    record = await db.get(IdempotencyKey, key)
    if record and record.expires_at <= datetime.utcnow():
        await db.delete(record)
        await db.flush()
        return None
    return record


def scoped_idempotency_key(business_id: int, key: str) -> str:
    scope = json.dumps([business_id, "POST /api/v1/appointments", key])
    return "v1:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()


async def create_idempotency_key(
    db: AsyncSession,
    key: str,
    business_id: int,
    request_payload: dict,
    expiration_minutes: int = 1440 # 24 hours
) -> IdempotencyKey:
    """Creates a new idempotency key record."""
    request_hash = hashlib.sha256(json.dumps(request_payload, sort_keys=True).encode('utf-8')).hexdigest()
    expires_at = datetime.utcnow() + timedelta(minutes=expiration_minutes)
    
    idempotency_record = IdempotencyKey(
        idempotency_key=key,
        business_id=business_id,
        request_hash=request_hash,
        expires_at=expires_at
    )
    db.add(idempotency_record)
    # Commit the key and appointment atomically in the caller.
    await db.flush()
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
    await db.flush()
