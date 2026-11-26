import secrets
from datetime import datetime
from typing import Annotated, Optional

from fastapi import Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from exceptions import InvalidApiKeyError, UnauthorizedError
from models import ApiKey, User, Business


def can_access_workspace(user: Optional[User]) -> bool:
    return bool(
        user and user.role in {"owner", "admin"} and getattr(user, "business_id", None) and user.business
        and user.business.is_active and not getattr(user, "is_demo_workspace", False)
    )


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    from services.demo_workspace import DEMO_SESSION_KEY, DEMO_USER_ID

    demo = getattr(request.state, "demo_workspace", False)
    uid = DEMO_USER_ID if demo else request.session.get("user_id")
    if not isinstance(uid, int):
        request.session.pop("user_id", None)
        return None
    user = await db.get(User, uid)
    if user and user.business_id:
        user.business = await db.get(Business, user.business_id)
        if not user.business or not user.business.is_active:
            user = None
    if not user:
        request.session.pop(DEMO_SESSION_KEY if demo else "user_id", None)
        return None
    user.is_demo_workspace = demo
    return user


class APIKeyAuth:
    """
    FastAPI dependency to authenticate API keys and provide tenant context.
    """
    def __init__(self, required: bool = True):
        self.required = required

    async def __call__(self,
                       request: Request,
                       x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
                       db: AsyncSession = Depends(get_db)) -> int:
        """
        Authenticates the API key and returns the business_id (tenant_id).
        """
        if not x_api_key:
            if self.required:
                raise InvalidApiKeyError("X-API-Key header is missing")
            return None

        # Directly query for the API key
        # Note: For production, consider adding a cache layer (e.g., Redis)
        # to reduce DB load for frequent API key lookups.
        authenticated_key = await db.scalar(
            select(ApiKey).join(Business, Business.id == ApiKey.business_id).where(
                ApiKey.api_key == x_api_key,
                ApiKey.is_active == True,
                Business.is_active == True,
            )
        )

        if not authenticated_key:
            raise InvalidApiKeyError("Invalid or inactive API key")

        # Update last_used_at
        authenticated_key.last_used_at = datetime.now()
        await db.commit()
        await db.refresh(authenticated_key)

        # Store business_id in request state for easy access in routes
        request.state.business_id = authenticated_key.business_id
        request.state.api_key_id = authenticated_key.id

        return authenticated_key.business_id

# Create an instance for easy use in routes
get_tenant_context = APIKeyAuth(required=True)
