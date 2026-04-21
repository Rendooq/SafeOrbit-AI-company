from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field

# --- API Key Schemas ---

class ApiKeyCreate(BaseModel):
    name: str = Field(..., description="A human-readable name for the API key")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Integration Key - Website"
            }
        }

class ApiKeyResponse(BaseModel):
    id: int
    api_key: str = Field(..., description="The full API key") # Now includes the full key
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ApiKeyFullResponse(ApiKeyResponse):
    # api_key is already in ApiKeyResponse, no need for a separate 'key' field
    pass

# --- Appointment Schemas ---

class AppointmentBase(BaseModel):
    customer_id: int = Field(..., description="ID of the customer associated with the appointment")
    master_id: Optional[int] = Field(None, description="ID of the master for the appointment")
    appointment_time: datetime = Field(..., description="Scheduled time of the appointment (ISO 8601 format)")
    service_type: str = Field(..., description="Type or name of the service")
    cost: float = Field(0.0, description="Cost of the service")
    source: str = Field("api", description="Source of the appointment (e.g., 'api', 'webhook')")
    delivery_address: Optional[str] = Field(None, description="Delivery address for retail businesses")
    ttn: Optional[str] = Field(None, description="Tracking number for delivery")
    delivery_status: str = Field("pending", description="Status of the delivery")

class AppointmentCreate(AppointmentBase):
    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": 42,
                "master_id": 5,
                "appointment_time": "2026-04-20T14:30:00",
                "service_type": "Манікюр",
                "cost": 550.0
            }
        }

class AppointmentUpdate(BaseModel):
    customer_id: Optional[int] = None
    master_id: Optional[int] = None
    appointment_time: Optional[datetime] = None
    service_type: Optional[str] = None
    status: Optional[str] = None
    cost: Optional[float] = None
    source: Optional[str] = None
    delivery_address: Optional[str] = None
    ttn: Optional[str] = None
    delivery_status: Optional[str] = None

class AppointmentResponse(AppointmentBase):
    id: int
    business_id: int
    status: str
    reminder_sent: bool
    followup_sent: bool

    class Config:
        from_attributes = True

# --- Customer Schemas ---

class CustomerBase(BaseModel):
    name: Optional[str] = Field(None, description="Customer's full name")
    phone_number: str = Field(..., description="Customer's phone number")
    notes: Optional[str] = Field(None, description="Internal notes about the customer")
    discount_percent: float = Field(0.0, description="Personal discount percentage for the customer")
    is_blocked: bool = Field(False, description="Whether the customer is blocked from booking")

class CustomerCreate(CustomerBase):
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Олена Коваленко",
                "phone_number": "+380501234567",
                "notes": "VIP клієнт",
                "discount_percent": 10.0
            }
        }

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    notes: Optional[str] = None
    discount_percent: Optional[float] = None
    is_blocked: Optional[bool] = None

class CustomerResponse(CustomerBase):
    id: int
    business_id: int
    telegram_id: Optional[str] = None

    class Config:
        from_attributes = True

# --- Webhook Schemas ---

class WebhookEvent(BaseModel):
    event_type: str = Field(..., description="Type of the event (e.g., 'appointment.created', 'message.received')")
    payload: dict = Field(..., description="Event-specific data")
    timestamp: datetime = Field(..., description="Timestamp when the event occurred")
    # Add any other common fields expected in your webhook events

class WebhookEndpointCreate(BaseModel):
    url: str = Field(..., description="HTTPS URL to receive webhook events")

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://your-server.com/api/webhooks"
            }
        }

class WebhookEndpointResponse(BaseModel):
    id: int
    business_id: int
    url: str
    secret: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# --- Generic Error Response ---

class ErrorDetail(BaseModel):
    code: str = Field(..., description="A unique error code (e.g., 'invalid_api_key')")
    message: str = Field(..., description="A human-readable error message")

class ErrorResponse(BaseModel):
    error: ErrorDetail

# --- Health Check Response ---

class HealthCheckResponse(BaseModel):
    status: str = Field(..., example="ok")
    database: str = Field(..., example="connected")
    message_queue: str = Field(..., example="not_configured") # Or "connected" if MQ is used
    cache: str = Field(..., example="not_configured") # Or "connected" if Cache is used
    version: str = Field(..., example="1.0.0")
    timestamp: datetime

# --- Idempotency Key Headers ---

class IdempotencyKeyHeader(BaseModel):
    idempotency_key: str = Field(
        ...,
        alias="Idempotency-Key",
        description="A unique key to ensure idempotency for POST requests. Max 255 characters.",
        max_length=255
    )

    class Config:
        populate_by_name = True

# --- Educational API Schemas ---

class MessageIn(BaseModel):
    message: str = Field(..., description="User's message to the educational bot")
    user_id: str = Field(..., description="Unique identifier for the user")
    channel: str = Field(..., description="Channel from which the message originated (e.g., 'telegram', 'web')")

class MessageOut(BaseModel):
    reply: str = Field(..., description="The bot's reply")
    intent: str = Field(..., description="Detected intent of the user's message")
    extracted_data: "ExtractedData" = Field(..., description="Extracted entities from the message")

class ExtractedData(BaseModel):
    course: Optional[str] = Field(None, description="Extracted course name")
    date: Optional[str] = Field(None, description="Extracted date (YYYY-MM-DD or DD.MM)")
    time: Optional[str] = Field(None, description="Extracted time (HH:MM)")

class BookingIn(BaseModel):
    student_name: str = Field(..., description="Name of the student")
    phone: str = Field(..., description="Phone number of the student")
    course: str = Field(..., description="Name of the course to book")
    date: str = Field(..., description="Desired booking date (YYYY-MM-DD)")
    time: str = Field(..., description="Desired booking time (HH:MM)")
    teacher_id: Optional[int] = Field(None, description="ID of the preferred teacher")

class BookingOut(BaseModel):
    status: str = Field(..., description="Status of the booking operation")
    message: str = Field(..., description="Detailed message about the booking result")
    booking_id: Optional[int] = Field(None, description="ID of the created booking, if successful")

class WebhookIn(BaseModel):
    event: str = Field(..., description="Type of event from the ERP system (e.g., 'student_created', 'schedule_updated')")
    data: Dict[str, Any] = Field(..., description="Payload of the event")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp of the event")

class WebhookOut(BaseModel):
    status: str = Field(..., description="Status of webhook processing")
    message: Optional[str] = Field(None, description="Optional message about processing")

class HealthCheck(BaseModel):
    status: str = Field(..., example="ok")


# Update forward references for MessageOut
MessageOut.model_rebuild()