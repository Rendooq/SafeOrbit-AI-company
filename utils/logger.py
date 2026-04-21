from sqlalchemy.ext.asyncio import AsyncSession
from models import ActionLog

async def log_action(db: AsyncSession, business_id: int, user_id: int, action: str, details: str):
    try:
        log = ActionLog(business_id=business_id, user_id=user_id, action=action, details=details)
        db.add(log)
        await db.commit()
    except Exception:
        pass