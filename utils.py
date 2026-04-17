import hashlib
import secrets
from typing import Optional # Keep Optional for log_action

from sqlalchemy.ext.asyncio import AsyncSession

from models import ActionLog


def hash_password(password: str) -> str:
    """Hashes a password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, stored_password: str) -> bool:
    """
    Verifies a plain password against a stored hash.
    Handles both direct hash comparison and legacy hash comparison.
    """
    # compare_digest(str) allows only ASCII; UTF-8 bytes for passwords with Cyrillic etc.
    if secrets.compare_digest(
        plain_password.encode("utf-8"),
        stored_password.encode("utf-8"),
    ):
        return True
    try:
        # Legacy check for already hashed passwords
        return secrets.compare_digest(
            hash_password(plain_password).encode("ascii"),
            stored_password.encode("ascii"),
        )
    except UnicodeEncodeError:
        return False

async def log_action(db: AsyncSession, biz_id: int, user_id: Optional[int], action: str, details: str):
    """Logs an action to the database."""
    new_log = ActionLog(business_id=biz_id, user_id=user_id, action=action, details=details)
    db.add(new_log)
    await db.commit()