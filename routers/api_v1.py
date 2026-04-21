import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import List, Optional
import logging

from fastapi import APIRouter, Body, Depends, Header, Request, Response, status, BackgroundTasks
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import WEBHOOK_SIGNING_SECRET, UA_TZ
from database import get_db
from dependencies import get_tenant_context
from exceptions import (APIError, IdempotencyKeyError, InvalidApiKeyError,
                        NotFoundError, WebhookSignatureError)
from models import ApiKey, Appointment, Business, Customer, IdempotencyKey, WebhookEndpoint
from schemas import (ApiKeyCreate, ApiKeyFullResponse, ApiKeyResponse, CustomerCreate, CustomerResponse, CustomerUpdate, WebhookEndpointCreate, WebhookEndpointResponse,
                     AppointmentCreate, AppointmentResponse, AppointmentUpdate,
                     HealthCheckResponse, WebhookEvent)
from utils.security import generate_api_key
from services.idempotency import (create_idempotency_key, get_idempotency_key,
                                  update_idempotency_key)
from services.webhooks import dispatch_webhooks

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(api_key_header)])

# --- API Key Endpoints ---

@router.post(
    "/api-keys",
    response_model=ApiKeyFullResponse,
    status_code=status.HTTP_200_OK, # Changed to 200 OK as per Stripe's API for key creation
    tags=["API Keys"],
    summary="Згенерувати новий API ключ",
    description="Створює новий Stripe-like секретний ключ (`sk_live_...`) для доступу до API. Збережіть його, оскільки він повертається лише один раз.",
)
async def create_api_key(
    api_key_data: ApiKeyCreate,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    new_api_key_value = generate_api_key()
    
    new_api_key = ApiKey(
        business_id=business_id,
        api_key=new_api_key_value, # Store the key directly
        name=api_key_data.name,
        is_active=True,
        created_at=datetime.now()
    )
    db.add(new_api_key)
    await db.commit()
    await db.refresh(new_api_key)
    return new_api_key


@router.get(
    "/api-keys",
    response_model=List[ApiKeyResponse],
    tags=["API Keys"],
    summary="Список API ключів",
    description="Отримує список усіх активних та неактивних API ключів вашого бізнесу.",
)
async def list_api_keys(
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ApiKey).where(ApiKey.business_id == business_id)
    api_keys = (await db.execute(stmt)).scalars().all() 
    return api_keys 


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["API Keys"],
    summary="Відкликати API ключ",
    description="Миттєво деактивує API ключ, роблячи його недійсним для майбутніх запитів.",
)
async def revoke_api_key(
    key_id: int,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    api_key = await db.get(ApiKey, key_id)
    if not api_key or api_key.business_id != business_id:
        raise NotFoundError("API key not found")
    
    api_key.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Webhooks Management Endpoints ---

@router.post(
    "/webhooks",
    response_model=WebhookEndpointResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Webhooks"],
    summary="Створити Webhook Endpoint",
    description="Реєструє новий URL для отримання подій в реальному часі. Повертає `secret` для перевірки підпису.",
)
async def create_webhook_endpoint(
    endpoint_data: WebhookEndpointCreate,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    secret = f"whsec_{secrets.token_hex(24)}"
    new_endpoint = WebhookEndpoint(
        business_id=business_id,
        url=endpoint_data.url,
        secret=secret
    )
    db.add(new_endpoint)
    await db.commit()
    await db.refresh(new_endpoint)
    return new_endpoint

@router.get(
    "/webhooks",
    response_model=List[WebhookEndpointResponse],
    tags=["Webhooks"],
    summary="Список Webhook Endpoints",
)
async def list_webhook_endpoints(
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    endpoints = (await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.business_id == business_id))).scalars().all()
    return endpoints

@router.delete(
    "/webhooks/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Webhooks"],
    summary="Видалити Webhook Endpoint",
)
async def delete_webhook_endpoint(
    endpoint_id: int,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.business_id != business_id:
        raise NotFoundError("Webhook endpoint not found")
    await db.delete(endpoint)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Appointments Endpoints ---

@router.get(
    "/appointments",
    response_model=List[AppointmentResponse],
    tags=["Appointments"],
    summary="Отримати список записів",
    description="""
Повертає всі записи (appointments).
Можна фільтрувати за статусом:
- `status=confirmed`
- `status=completed`
""",
)
async def list_appointments(
    status: Optional[str] = None,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Appointment).where(Appointment.business_id == business_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    
    appointments = (await db.execute(stmt)).scalars().all()
    return appointments


@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Appointments"],
    summary="Створити новий запис",
    description="Створює новий запис (appointment). Підтримує ідемпотентність через заголовок `Idempotency-Key`.",
)
async def create_appointment(
    appointment_data: AppointmentCreate,
    background_tasks: BackgroundTasks,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    if idempotency_key:
        existing_idempotency_record = await get_idempotency_key(db, idempotency_key)
        
        request_payload_hash = hashlib.sha256(
            json.dumps(appointment_data.model_dump(), sort_keys=True).encode('utf-8')
        ).hexdigest()

        if existing_idempotency_record:
            if existing_idempotency_record.request_hash != request_payload_hash:
                raise IdempotencyKeyError("Idempotency key already used with a different request payload.")
            
            # Return stored response if available
            if existing_idempotency_record.response_data:
                return Response(
                    content=existing_idempotency_record.response_data,
                    status_code=existing_idempotency_record.status_code,
                    media_type="application/json"
                )
            else:
                # Request is in progress, or failed without a stored response.
                # For simplicity, we'll treat this as a conflict.
                raise IdempotencyKeyError("Request with this idempotency key is already being processed or failed.")
        else:
            # Create new idempotency record
            await create_idempotency_key(db, idempotency_key, business_id, appointment_data.model_dump())

    # Basic validation for customer_id existence
    customer = await db.get(Customer, appointment_data.customer_id)
    if not customer or customer.business_id != business_id:
        raise APIError(code="invalid_customer", message="Customer not found or does not belong to this business")

    new_appointment = Appointment(business_id=business_id, **appointment_data.model_dump())
    db.add(new_appointment)
    await db.commit()
    await db.refresh(new_appointment)

    if idempotency_key:
        idempotency_record = await get_idempotency_key(db, idempotency_key)
        if idempotency_record:
            await update_idempotency_key(db, idempotency_record, {"id": new_appointment.id, "status": new_appointment.status}, status.HTTP_201_CREATED)

    # Trigger webhook in background
    background_tasks.add_task(
        dispatch_webhooks,
        business_id,
        "appointment.created",
        {"id": new_appointment.id, "customer_id": new_appointment.customer_id, "service": new_appointment.service_type, "time": new_appointment.appointment_time.isoformat()}
    )
    return new_appointment


@router.get(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    tags=["Appointments"],
    summary="Отримати запис за ID",
    description="Повертає деталі конкретного запису за його ідентифікатором.",
)
async def retrieve_appointment(
    appointment_id: int,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.business_id != business_id:
        raise NotFoundError("Appointment not found")
    return appointment


@router.put(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    tags=["Appointments"],
    summary="Оновити запис",
    description="Оновлює існуючий запис. Усі поля є опціональними, оновлюються лише передані.",
)
async def update_appointment(
    appointment_id: int,
    appointment_data: AppointmentUpdate,
    background_tasks: BackgroundTasks,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.business_id != business_id:
        raise NotFoundError("Appointment not found")
    
    for field, value in appointment_data.model_dump(exclude_unset=True).items():
        setattr(appointment, field, value)
    
    await db.commit()
    await db.refresh(appointment)

    background_tasks.add_task(
        dispatch_webhooks,
        business_id,
        "appointment.updated",
        {"id": appointment.id, "status": appointment.status, "service": appointment.service_type, "time": appointment.appointment_time.isoformat()}
    )
    return appointment


@router.delete(
    "/appointments/{appointment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Appointments"],
    summary="Видалити запис",
    description="Повністю видаляє запис з бази даних.",
)
async def delete_appointment(
    appointment_id: int,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.business_id != business_id:
        raise NotFoundError("Appointment not found")
    
    await db.delete(appointment)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Customers Endpoints ---

@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Customers"],
    summary="Створити клієнта",
    description="Створює нового клієнта у вашій базі. Номер телефону має бути унікальним.",
)
async def create_customer(
    customer_data: CustomerCreate,
    background_tasks: BackgroundTasks,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    # Check if customer with this phone number already exists for the tenant
    existing_customer = await db.scalar(
        select(Customer).where(
            and_(
                Customer.business_id == business_id,
                Customer.phone_number == customer_data.phone_number
            )
        )
    )
    if existing_customer:
        raise APIError(code="customer_already_exists", message="A customer with this phone number already exists.", status_code=status.HTTP_409_CONFLICT)

    new_customer = Customer(business_id=business_id, **customer_data.model_dump())
    db.add(new_customer)
    await db.commit()
    await db.refresh(new_customer)

    background_tasks.add_task(
        dispatch_webhooks,
        business_id,
        "customer.created",
        {"id": new_customer.id, "name": new_customer.name, "phone_number": new_customer.phone_number}
    )
    return new_customer


@router.get(
    "/customers",
    response_model=List[CustomerResponse],
    tags=["Customers"],
    summary="Список клієнтів",
    description="Повертає список усіх клієнтів вашого бізнесу.",
)
async def list_customers(
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Customer).where(Customer.business_id == business_id)
    customers = (await db.execute(stmt)).scalars().all()
    return customers


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    tags=["Customers"],
    summary="Отримати клієнта за ID",
    description="Повертає детальну інформацію про клієнта.",
)
async def retrieve_customer(
    customer_id: int,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    customer = await db.get(Customer, customer_id)
    if not customer or customer.business_id != business_id:
        raise NotFoundError("Customer not found")
    return customer


@router.put(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    tags=["Customers"],
    summary="Оновити дані клієнта",
    description="Оновлює картку клієнта (знижки, нотатки, статус блокування).",
)
async def update_customer_api(
    customer_id: int,
    customer_data: CustomerUpdate,
    background_tasks: BackgroundTasks,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    customer = await db.get(Customer, customer_id)
    if not customer or customer.business_id != business_id:
        raise NotFoundError("Customer not found")

    for field, value in customer_data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)

    await db.commit()
    await db.refresh(customer)

    background_tasks.add_task(
        dispatch_webhooks,
        business_id,
        "customer.updated",
        {"id": customer.id, "name": customer.name, "phone_number": customer.phone_number}
    )
    return customer


@router.delete(
    "/customers/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Customers"],
    summary="Видалити клієнта",
    description="Видаляє клієнта. Зверніть увагу: дія неможлива, якщо у клієнта є прив'язані записи.",
)
async def delete_customer(
    customer_id: int,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    customer = await db.get(Customer, customer_id)
    if not customer or customer.business_id != business_id:
        raise NotFoundError("Customer not found")
    
    # Note: This will fail with a ForeignKeyViolationError if the customer has appointments.
    # A soft-delete (`is_deleted` flag) is a safer production pattern.
    await db.delete(customer)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Health Check ---

@router.get(
    "/health",
    response_model=HealthCheckResponse,
    tags=["System"],
    summary="Перевірка статусу системи",
    description="Перевіряє доступність API та підключення до бази даних.",
)
async def health_check(db: AsyncSession = Depends(get_db)):
    db_status = "disconnected"
    try:
        # Try to execute a simple query to check DB connection
        await db.execute(select(1))
        db_status = "connected"
    except Exception:
        pass

    # In a real app, you'd check MQ, cache, etc.
    return HealthCheckResponse(
        status="ok",
        database=db_status,
        message_queue="not_configured", # Placeholder
        cache="not_configured", # Placeholder
        version="1.0.0",
        timestamp=datetime.now(UA_TZ)
    )

# --- Webhooks ---

@router.post(
    "/webhooks/events",
    status_code=status.HTTP_200_OK,
    tags=["Webhooks"],
    summary="Отримати Webhook події",
    description="Ендпоінт для отримання подій (наприклад, `appointment.created`). Запит має містити коректний `X-Webhook-Signature`.",
)
async def receive_webhook_event(
    request: Request,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db)
):
    # Read raw body for signature verification
    body = await request.body()
    
    # --- Webhook Signature Verification ---
    if not x_webhook_signature:
        raise WebhookSignatureError("X-Webhook-Signature header is missing")

    # Calculate expected signature
    # This assumes a simple HMAC-SHA256 signature. Adjust based on provider's spec.
    # The secret should be unique per tenant if possible, or a global one.
    # For this example, we'll use a global secret from config.
    # In a multi-tenant setup, you'd typically extract tenant_id from the webhook payload
    # or URL, then fetch their specific webhook secret from the DB.
    
    # For demonstration, let's assume the webhook URL might contain business_id:
    # e.g., /api/v1/webhooks/events/{business_id}
    # For now, we'll use a global secret.
    
    expected_signature = hmac.new(
        WEBHOOK_SIGNING_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()

    if not secrets.compare_digest(expected_signature, x_webhook_signature):
        raise WebhookSignatureError("Invalid webhook signature")

    # --- Process Webhook Payload ---
    try:
        event_data = json.loads(body)
        # Validate with Pydantic schema
        webhook_event = WebhookEvent(**event_data)
    except json.JSONDecodeError:
        raise APIError(code="invalid_payload", message="Invalid JSON payload", status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        raise APIError(code="invalid_event_data", message=f"Invalid webhook event data: {e}", status_code=status.HTTP_400_BAD_REQUEST)

    # --- Route to Message Queue for Asynchronous Processing ---
    # In a real system, you would push this `webhook_event` to a message queue (e.g., RabbitMQ, Kafka)
    # for asynchronous processing by background workers.
    # This ensures the webhook endpoint responds quickly and doesn't block.
    
    # Example:
    # await message_queue.publish("webhook_events", webhook_event.model_dump_json())
    
    # For now, we'll just log it.
    logger.info(f"Received and verified webhook event: {webhook_event.event_type}")
    
    return {"message": "Webhook event received and processed successfully"}