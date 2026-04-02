from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from database import get_db
from models import User


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Dependency to get the current user from the session.
    Returns the User object or None if not authenticated.
    """
    uid = request.session.get("user_id")
    if not uid:
        return None
    res = await db.execute(select(User).options(joinedload(User.business)).where(User.id == uid))
    return res.scalar_one_or_none()