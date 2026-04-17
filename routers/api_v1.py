import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Header, Request, Response, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import WEBHOOK_SIGNING_SECRET, UA_TZ
from database import get_db
from dependencies import get_tenant_context
from exceptions import (APIError, IdempotencyKeyError, InvalidApiKeyError,
                        NotFoundError, WebhookSignatureError)
from models import ApiKey, Appointment, Business, Customer, IdempotencyKey
from schemas import (ApiKeyCreate, ApiKeyFullResponse, ApiKeyResponse, CustomerCreate, CustomerResponse, CustomerUpdate,
                     AppointmentCreate, AppointmentResponse, AppointmentUpdate,
                     HealthCheckResponse, IdempotencyKeyHeader, WebhookEvent)
from services.idempotency import (create_idempotency_key, get_idempotency_key,
                                  update_idempotency_key)

router = APIRouter(prefix="/api/v1", tags=["API v1"])

# --- API Key Endpoints ---

@router.post(
    "/api-keys",
    response_model=ApiKeyFullResponse,
    status_code=status.HTTP_200_OK, # Changed to 200 OK as per Stripe's API for key creation
    summary="Create a new API key",
    description="Generates a new secret API key for the current business. The full key is only returned once.",
    responses={
        201: {"description": "API key created successfully"},
        401: {"description": "Invalid API key"},
    }
)
async def create_api_key(
    api_key_data: ApiKeyCreate,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    new_api_key_value = f"sk_live_{secrets.token_hex(32)}"
    
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
    # Return the full ApiKey object, which now includes the 'api_key' field
    return ApiKeyFullResponse(**new_api_key.model_dump())


@router.get(
    "/api-keys",
    response_model=List[ApiKeyResponse],
    summary="List API keys",
    description="Retrieves a list of all API keys associated with the current business (excluding the full key).",
    responses={
        200: {"description": "List of API keys"},
        401: {"description": "Invalid API key"},
    }
)
async def list_api_keys(
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ApiKey).where(ApiKey.business_id == business_id)
    api_keys = (await db.execute(stmt)).scalars().all() # All keys are now fully visible
    return [ApiKeyResponse(**key.model_dump()) for key in api_keys] # Pydantic will handle the 'api_key' field


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description="Deactivates an API key, making it unusable for future requests.",
    responses={
        204: {"description": "API key revoked successfully"},
        401: {"description": "Invalid API key"},
        404: {"description": "API key not found"},
    }
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

# --- Appointments Endpoints ---

@router.get(
    "/appointments",
    response_model=List[AppointmentResponse],
    summary="List appointments",
    description="Retrieves a list of appointments for the current business, optionally filtered by status.",
    responses={
        200: {"description": "List of appointments"},
        401: {"description": "Invalid API key"},
    }
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
    return [AppointmentResponse(**appt.model_dump()) for appt in appointments]


@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an appointment",
    description="Creates a new appointment for the current business. Supports idempotency via `Idempotency-Key` header.",
    responses={
        201: {"description": "Appointment created successfully"},
        401: {"description": "Invalid API key"},
        409: {"description": "Idempotency key mismatch or already processed"},
    }
)
async def create_appointment(
    appointment_data: AppointmentCreate,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db),
    idempotency_key_header: Optional[IdempotencyKeyHeader] = Header(None, alias="Idempotency-Key")
):
    if idempotency_key_header and idempotency_key_header.idempotency_key:
        idempotency_key = idempotency_key_header.idempotency_key
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

    response_data = AppointmentResponse(**new_appointment.model_dump()).model_dump_json()
    
    if idempotency_key_header and idempotency_key_header.idempotency_key:
        idempotency_record = await get_idempotency_key(db, idempotency_key_header.idempotency_key)
        if idempotency_record:
            await update_idempotency_key(db, idempotency_record, json.loads(response_data), status.HTTP_201_CREATED)

    return Response(content=response_data, status_code=status.HTTP_201_CREATED, media_type="application/json")


@router.get(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Retrieve an appointment",
    description="Retrieves a specific appointment by its ID.",
    responses={
        200: {"description": "Appointment details"},
        401: {"description": "Invalid API key"},
        404: {"description": "Appointment not found"},
    }
)
async def retrieve_appointment(
    appointment_id: int,
    business_id: int = Depends(get_tenant_context), # This now works correctly
    db: AsyncSession = Depends(get_db)
):
    appointment = await db.get(Appointment, appointment_id)
    if not appointment or appointment.business_id != business_id:
        raise NotFoundError("Appointment not found")
    return AppointmentResponse(**appointment.model_dump())


@router.put(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Update an appointment",
    description="Updates an existing appointment by its ID.",
    responses={
        200: {"description": "Appointment updated successfully"},
        401: {"description": "Invalid API key"},
        404: {"description": "Appointment not found"},
    }
)
async def update_appointment(
    appointment_id: int,
    appointment_data: AppointmentUpdate,
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
    return AppointmentResponse(**appointment.model_dump())


@router.delete(
    "/appointments/{appointment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an appointment",
    description="Deletes an appointment by its ID.",
    responses={
        204: {"description": "Appointment deleted successfully"},
        401: {"description": "Invalid API key"},
        404: {"description": "Appointment not found"},
    }
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
    summary="Create a customer",
    description="Creates a new customer for the current business.",
)
async def create_customer(
    customer_data: CustomerCreate,
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
    return CustomerResponse(**new_customer.model_dump())


@router.get(
    "/customers",
    response_model=List[CustomerResponse],
    summary="List customers",
    description="Retrieves a list of customers for the current business.",
)
async def list_customers(
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Customer).where(Customer.business_id == business_id)
    customers = (await db.execute(stmt)).scalars().all()
    return [CustomerResponse(**cust.model_dump()) for cust in customers]


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    summary="Retrieve a customer",
    description="Retrieves a specific customer by their ID.",
)
async def retrieve_customer(
    customer_id: int,
    business_id: int = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db)
):
    customer = await db.get(Customer, customer_id)
    if not customer or customer.business_id != business_id:
        raise NotFoundError("Customer not found")
    return CustomerResponse(**customer.model_dump())


@router.put(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    summary="Update a customer",
    description="Updates an existing customer by their ID.",
)
async def update_customer_api(
    customer_id: int,
    customer_data: CustomerUpdate,
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
    return CustomerResponse(**customer.model_dump())


@router.delete(
    "/customers/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a customer",
    description="Deletes a customer by their ID. This is a destructive action and will fail if the customer has associated appointments.",
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
    summary="Health check",
    description="Checks the health and status of the API and its dependencies.",
    responses={
        200: {"description": "API is healthy"},
        500: {"description": "API is unhealthy"},
    }
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
    summary="Receive webhook events",
    description="Endpoint for receiving and processing webhook events from external services.",
    responses={
        200: {"description": "Webhook event received and processed"},
        401: {"description": "Invalid webhook signature"},
    }
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
    print(f"Received and verified webhook event: {webhook_event.event_type} for business_id (if extracted): N/A")
    
    return {"message": "Webhook event received and processed successfully"}