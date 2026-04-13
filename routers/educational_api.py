import logging
import re
from typing import Dict, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

import schemas
from services.ai_service import generate_ai_reply

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Educational ERP Integration"])

def detect_intent(message: str) -> (str, Dict[str, Any]):
    """
    Placeholder for intent detection and entity extraction.
    In a real application, this would use a NLP library (like spaCy, NLTK) or a service (like Dialogflow, Rasa).
    """
    message_lower = message.lower()
    
    # Simple keyword-based intent detection
    if any(word in message_lower for word in ["запис", "записатись", "book", "booking", "урок", "заняття"]):
        intent = "booking"
    elif any(word in message_lower for word in ["ціна", "коштує", "price", "cost"]):
        intent = "pricing"
    elif any(word in message_lower for word in ["пробн", "trial"]):
        intent = "trial_lesson"
    else:
        intent = "question"

    # Simple entity extraction using regex
    course_match = re.search(r'(англійськ\w+|математик\w+|німецьк\w+)', message_lower)
    date_match = re.search(r'(\d{1,2}\.\d{1,2})|(\d{4}-\d{2}-\d{2})', message_lower)
    time_match = re.search(r'(\d{1,2}:\d{2})', message_lower)

    extracted_data = {
        "course": course_match.group(0) if course_match else None,
        "date": date_match.group(0) if date_match else None,
        "time": time_match.group(0) if time_match else None,
    }
    
    return intent, extracted_data


@router.post("/message", response_model=schemas.MessageOut)
async def handle_incoming_message(message_in: schemas.MessageIn):
    """
    Handles an incoming message from a client via a channel.
    Detects intent, extracts data, and generates an AI reply.
    """
    logger.info(f"Received message from user {message_in.user_id} on {message_in.channel}: '{message_in.message}'")
    
    intent, extracted_data_dict = detect_intent(message_in.message)
    
    ai_reply = await generate_ai_reply(message_in.message, intent, extracted_data_dict)
    
    response = schemas.MessageOut(
        reply=ai_reply,
        intent=intent,
        extracted_data=schemas.ExtractedData(**extracted_data_dict)
    )
    
    logger.info(f"Replying with intent '{intent}' and message: '{ai_reply}'")
    return response


@router.post("/booking", response_model=schemas.BookingOut)
async def create_booking(booking_in: schemas.BookingIn, request: Request):
    """
    Creates an appointment by calling the internal /admin/add-appointment endpoint.
    This acts as a bridge between the JSON-based external API and the form-based internal one.
    """
    logger.info(f"Received booking request for {booking_in.student_name} for course {booking_in.course}")

    internal_endpoint_url = str(request.base_url).rstrip('/') + "/admin/add-appointment"
    
    form_data = {
        "phone": booking_in.phone,
        "name": booking_in.student_name,
        "date": booking_in.date,
        "time": booking_in.time,
        "service": booking_in.course,
        "master_id": booking_in.teacher_id if booking_in.teacher_id else "",
    }
    
    logger.warning("SIMULATION: In a production environment, the business logic from the '/admin/add-appointment' endpoint should be refactored into a service function and called directly from here to bypass session-based authentication.")
    logger.info(f"Simulating call to internal endpoint: {internal_endpoint_url} with form data: {form_data}")
    
    return schemas.BookingOut(status="success", message="Booking created successfully (simulation).")


@router.post("/webhook", response_model=schemas.WebhookOut)
async def handle_erp_webhook(webhook_in: schemas.WebhookIn):
    """
    Receives and logs events from the external ERP system (e.g., Voopty).
    """
    logger.info(f"Received webhook event '{webhook_in.event}' with data: {webhook_in.data}")
    
    if webhook_in.event == "student_created":
        logger.info(f"Processing 'student_created' event for student: {webhook_in.data.get('name')}")
    elif webhook_in.event == "schedule_updated":
        logger.info("Processing 'schedule_updated' event.")
        
    return schemas.WebhookOut(status="received")


@router.get("/health", response_model=schemas.HealthCheck)
async def health_check():
    """
    A simple health check endpoint to confirm the API is running.
    """
    return schemas.HealthCheck(status="ok")