from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import select
from database import AsyncSessionLocal
from dependencies import get_current_user
from models import ActivationDocument, Business


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Starlette normalizes paths with os.path.join (backslashes on Windows).
        normalized = path.replace("\\", "/").lstrip("/")
        if normalized.startswith(("uploads/documents/", "uploads/receipts/", "receipts/")):
            request = Request(scope)
            async with AsyncSessionLocal() as db:
                user = await get_current_user(request, db)
                pending = request.session.get("pending_business_id")
                filename = "/static/" + normalized
                business = await db.scalar(select(Business).where(
                    (Business.receipt_url == filename) | (Business.nda_url == filename) | (Business.contract_url == filename)
                ))
                allowed = business and (
                    (user and (user.role == "superadmin" or user.business_id == business.id or
                               (user.role == "owner" and business.parent_id == user.business_id)))
                    or (isinstance(pending, int) and pending == business.id)
                )
                if not allowed:
                    raise HTTPException(status_code=404)
                if normalized.startswith("uploads/documents/"):
                    document = await db.get(ActivationDocument, filename)
                    if document and document.business_id == business.id:
                        return Response(
                            document.content if request.method != "HEAD" else b"",
                            media_type="application/octet-stream",
                            headers={
                                "Cache-Control": "private, no-store",
                                "Content-Disposition": f'attachment; filename="{normalized.rsplit("/", 1)[-1]}"',
                                "Content-Length": str(len(document.content)),
                                "X-Content-Type-Options": "nosniff",
                            },
                        )
        if normalized.startswith(("uploads/photos/", "uploads/products/")) and not normalized.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        if normalized.startswith(("saas/", "vendor/", "v2/")):
            response.headers["Cache-Control"] = "public, max-age=86400"
        elif normalized.startswith("uploads/"):
            response.headers["Cache-Control"] = "private, no-store"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response
