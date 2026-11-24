from fastapi import HTTPException

from models import Master


TEAM_SCHEDULE_ROLES = {"Адміністратор", "Директор", "СЕО", "СОО"}


async def personal_schedule(user, db):
    """Regular specialists see their own bookings. Team-wide roles see the workspace."""
    if user.role != "master":
        return False
    master = await db.get(Master, user.master_id) if user.master_id else None
    if not master or not master.is_active or master.business_id != user.business_id:
        raise HTTPException(403)
    return master.role not in TEAM_SCHEDULE_ROLES
