import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from exceptions import RateLimitExceededError
from database import AsyncSessionLocal
from models import ApiRequestLog

logger = logging.getLogger(__name__)

# In-memory storage for rate limiting. For production, use Redis.
rate_limit_storage: Dict[str, Dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 100 # 100 requests per minute per API key

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Apply rate limiting only to API v1 routes
        if request.url.path.startswith("/api/v1/"):
            api_key_prefix = "unknown"
            # Try to get API key prefix from header (masked for logging)
            x_api_key = request.headers.get("X-API-Key")
            if x_api_key:
                parts = x_api_key.split('_', 2)
                if len(parts) == 3:
                    api_key_prefix = f"{parts[0]}_{parts[1]}_****"
            
            # Use the full (masked) API key as the identifier for rate limiting
            # In a real scenario, you might want to rate limit per business_id after authentication
            # but for pre-authentication rate limiting, the key itself is the identifier.
            # For simplicity here, we'll use the masked key.
            
            current_time = datetime.now().replace(second=0, microsecond=0) # Group by minute
            
            # Clean up old entries
            for timestamp in list(rate_limit_storage[api_key_prefix].keys()):
                if current_time - timestamp > timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS):
                    del rate_limit_storage[api_key_prefix][timestamp]
            
            rate_limit_storage[api_key_prefix][current_time] += 1
            
            total_requests_in_window = sum(rate_limit_storage[api_key_prefix].values())

            if total_requests_in_window > RATE_LIMIT_MAX_REQUESTS:
                raise RateLimitExceededError()

        response = await call_next(request)
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Mask API key for logging
        x_api_key = request.headers.get("X-API-Key")
        masked_api_key = "N/A"
        if x_api_key:
            parts = x_api_key.split('_', 2)
            if len(parts) == 3:
                masked_api_key = f"{parts[0]}_{parts[1]}_****{parts[2][-4:]}" # Show last 4 chars
            else:
                masked_api_key = "****" # Malformed key

        status_code = 500
        response = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"API Request Error: method={request.method} path={request.url.path} "
                f"api_key={masked_api_key} duration={process_time:.4f}s error={e}",
                exc_info=True
            )
            raise # Re-raise the exception after logging
        finally:
            # Логуємо запит до БД, якщо була використана API-автентифікація
            if hasattr(request.state, "api_key_id"):
                try:
                    async with AsyncSessionLocal() as db:
                        log = ApiRequestLog(
                            api_key_id=request.state.api_key_id,
                            business_id=request.state.business_id,
                            endpoint=request.url.path,
                            method=request.method,
                            status_code=status_code,
                            ip_address=request.client.host if request.client else None
                        )
                        db.add(log)
                        await db.commit()
                except Exception as db_err:
                    logger.error(f"Failed to save API request log: {db_err}")

        process_time = time.time() - start_time
        logger.info(
            f"API Request: method={request.method} path={request.url.path} "
            f"status={status_code} api_key={masked_api_key} "
            f"duration={process_time:.4f}s"
        )
        return response