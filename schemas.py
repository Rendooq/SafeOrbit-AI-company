from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any

# Models for /api/message
class MessageIn(BaseModel):
    user_id: str
    message: str
    channel: Literal["instagram", "telegram", "whatsapp"]

class ExtractedData(BaseModel):
    course: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None

class MessageOut(BaseModel):
    reply: str
    intent: Literal["question", "booking", "trial_lesson", "pricing", "other"]
    extracted_data: ExtractedData

# Models for /api/booking
class BookingIn(BaseModel):
    student_name: str
    phone: str
    course: str
    date: str
    time: str
    teacher_id: Optional[str] = None

class BookingOut(BaseModel):
    status: Literal["success", "error"]
    message: Optional[str] = None

# Models for /api/webhook
class WebhookIn(BaseModel):
    event: str
    data: Dict[str, Any]

class WebhookOut(BaseModel):
    status: Literal["received"]

# Model for /api/health
class HealthCheck(BaseModel):
    status: Literal["ok"]