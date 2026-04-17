from fastapi import HTTPException, status


class APIError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail={"error": {"code": code, "message": message}})


class InvalidApiKeyError(APIError):
    def __init__(self, message: str = "Invalid API key"):
        super().__init__(code="invalid_api_key", message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class UnauthorizedError(APIError):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(code="unauthorized", message=message, status_code=status.HTTP_403_FORBIDDEN)


class NotFoundError(APIError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND)


class IdempotencyKeyError(APIError):
    def __init__(self, message: str = "Idempotency key mismatch or already processed"):
        super().__init__(code="idempotency_key_error", message=message, status_code=status.HTTP_409_CONFLICT)


class RateLimitExceededError(APIError):
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(code="rate_limit_exceeded", message=message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


class WebhookSignatureError(APIError):
    def __init__(self, message: str = "Invalid webhook signature"):
        super().__init__(code="invalid_webhook_signature", message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class InternalServerError(APIError):
    def __init__(self, message: str = "Internal server error"):
        super().__init__(code="internal_server_error", message=message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)