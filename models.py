from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    type: Mapped[str] = mapped_column(Text, default="barbershop")
    retail_subcategory: Mapped[Optional[str]] = mapped_column(Text)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, default="Ви асистент Барбершопу.")
    has_ai_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_token: Mapped[Optional[str]] = mapped_column(Text)
    instagram_token: Mapped[Optional[str]] = mapped_column(Text)
    beauty_pro_token: Mapped[Optional[str]] = mapped_column(Text)
    beauty_pro_location_id: Mapped[Optional[str]] = mapped_column(Text)
    beauty_pro_api_url: Mapped[Optional[str]] = mapped_column(Text, default="https://api.beautypro.com/v1/appointments")
    integration_system: Mapped[Optional[str]] = mapped_column(Text, default="none")
    integration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    wins_token: Mapped[Optional[str]] = mapped_column(Text)
    wins_branch_id: Mapped[Optional[str]] = mapped_column(Text)
    doctor_eleks_token: Mapped[Optional[str]] = mapped_column(Text)
    doctor_eleks_clinic_id: Mapped[Optional[str]] = mapped_column(Text)
    altegio_token: Mapped[Optional[str]] = mapped_column(Text)
    altegio_company_id: Mapped[Optional[str]] = mapped_column(Text)
    altegio_service_id: Mapped[Optional[str]] = mapped_column(Text)  # New Altegio field
    altegio_master_id: Mapped[Optional[str]] = mapped_column(Text)  # New Altegio field
    cleverbox_token: Mapped[Optional[str]] = mapped_column(Text)
    cleverbox_location_id: Mapped[Optional[str]] = mapped_column(Text)
    cleverbox_api_url: Mapped[Optional[str]] = mapped_column(Text)
    appointer_token: Mapped[Optional[str]] = mapped_column(Text)
    appointer_location_id: Mapped[Optional[str]] = mapped_column(Text)
    easyweek_token: Mapped[Optional[str]] = mapped_column(Text)
    easyweek_location_id: Mapped[Optional[str]] = mapped_column(Text)
    trendis_token: Mapped[Optional[str]] = mapped_column(Text)
    trendis_location_id: Mapped[Optional[str]] = mapped_column(Text)
    miopane_token: Mapped[Optional[str]] = mapped_column(Text)
    miopane_location_id: Mapped[Optional[str]] = mapped_column(Text)
    clinica_web_token: Mapped[Optional[str]] = mapped_column(Text)
    clinica_web_clinic_id: Mapped[Optional[str]] = mapped_column(Text)
    integrica_token: Mapped[Optional[str]] = mapped_column(Text)
    integrica_location_id: Mapped[Optional[str]] = mapped_column(Text)
    integrica_api_url: Mapped[Optional[str]] = mapped_column(Text)
    luckyfit_token: Mapped[Optional[str]] = mapped_column(Text)
    uspacy_token: Mapped[Optional[str]] = mapped_column(Text)  # New uspacy integration field
    uspacy_workspace_id: Mapped[Optional[str]] = mapped_column(Text)  # New uspacy integration field
    monobank_token: Mapped[Optional[str]] = mapped_column(Text)
    wayforpay_key: Mapped[Optional[str]] = mapped_column(Text)
    fondy_merchant_id: Mapped[Optional[str]] = mapped_column(Text)
    fondy_secret_key: Mapped[Optional[str]] = mapped_column(Text)
    stripe_secret_key: Mapped[Optional[str]] = mapped_column(Text)
    facebook_token: Mapped[Optional[str]] = mapped_column(Text)
    openai_api_key: Mapped[Optional[str]] = mapped_column(Text)
    google_maps_api_key: Mapped[Optional[str]] = mapped_column(Text)
    binotel_key: Mapped[Optional[str]] = mapped_column(Text)
    binotel_secret: Mapped[Optional[str]] = mapped_column(Text)
    ringostat_token: Mapped[Optional[str]] = mapped_column(Text)
    twilio_sid: Mapped[Optional[str]] = mapped_column(Text)
    twilio_token: Mapped[Optional[str]] = mapped_column(Text)
    plan_type: Mapped[Optional[str]] = mapped_column(Text, default="plan1")
    contract_url: Mapped[Optional[str]] = mapped_column(Text)
    nda_url: Mapped[Optional[str]] = mapped_column(Text)
    admin_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    payment_status: Mapped[str] = mapped_column(Text, default="approved")
    receipt_url: Mapped[Optional[str]] = mapped_column(Text)
    working_hours: Mapped[Optional[str]] = mapped_column(Text, default="Пн-Нд: 09:00 - 20:00")
    groq_api_key: Mapped[Optional[str]] = mapped_column(Text)
    viber_token: Mapped[Optional[str]] = mapped_column(Text)
    whatsapp_token: Mapped[Optional[str]] = mapped_column(Text)
    sms_token: Mapped[Optional[str]] = mapped_column(Text)
    sms_sender_id: Mapped[Optional[str]] = mapped_column(Text)
    ai_model: Mapped[str] = mapped_column(Text, default="llama-3.3-70b-versatile")
    ai_temperature: Mapped[float] = mapped_column(Float, default=0.5)
    ai_max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    instagram_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    viber_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_email: Mapped[Optional[str]] = mapped_column(Text)
    telegram_notification_chat_id: Mapped[Optional[str]] = mapped_column(Text)
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_server: Mapped[Optional[str]] = mapped_column(Text)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    vapi_api_key: Mapped[Optional[str]] = mapped_column(Text)
    vapi_assistant_id: Mapped[Optional[str]] = mapped_column(Text)
    retell_api_key: Mapped[Optional[str]] = mapped_column(Text)
    transfer_phone_number: Mapped[Optional[str]] = mapped_column(Text)  # New field for call transfer
    retell_agent_id: Mapped[Optional[str]] = mapped_column(Text)
    smtp_username: Mapped[Optional[str]] = mapped_column(Text)
    smtp_password: Mapped[Optional[str]] = mapped_column(Text)
    smtp_sender: Mapped[Optional[str]] = mapped_column(Text)
    utm_source: Mapped[Optional[str]] = mapped_column(Text)
    utm_medium: Mapped[Optional[str]] = mapped_column(Text)
    utm_campaign: Mapped[Optional[str]] = mapped_column(Text)
    # Payment settings for super admin configuration
    payment_iban: Mapped[Optional[str]] = mapped_column(Text)
    payment_qr_url: Mapped[Optional[str]] = mapped_column(Text)
    payment_card_number: Mapped[Optional[str]] = mapped_column(Text)
    payment_receiver_name: Mapped[Optional[str]] = mapped_column(Text)
    subscription_discount: Mapped[int] = mapped_column(Integer, default=0)
    discount_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    webhook_secret: Mapped[Optional[str]] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    business_id: Mapped[Optional[int]] = mapped_column(ForeignKey("businesses.id"))
    master_id: Mapped[Optional[int]] = mapped_column(ForeignKey("masters.id"))
    tg_bot_token: Mapped[Optional[str]] = mapped_column(Text)
    tg_chat_id: Mapped[Optional[str]] = mapped_column(Text)
    last_updates_view_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    business = relationship("Business")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    phone_number: Mapped[str] = mapped_column(Text)
    name: Mapped[Optional[str]] = mapped_column(Text)
    telegram_id: Mapped[Optional[str]] = mapped_column(Text)
    support_status: Mapped[str] = mapped_column(Text, default="none")
    is_ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    photo_urls: Mapped[Optional[str]] = mapped_column(Text)
    discount_percent: Mapped[float] = mapped_column(Float, default=0.0)  # Default value included in model
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_reactivation_sent: Mapped[Optional[datetime]] = mapped_column(DateTime)


class MasterService(Base):
    __tablename__ = "master_services"
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), primary_key=True)


class Master(Base):
    __tablename__ = "masters"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="Експерт")
    altegio_master_id: Mapped[Optional[str]] = mapped_column(Text)  # New field for Altegio mapping
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(Text)
    personal_bot_token: Mapped[Optional[str]] = mapped_column(Text)
    commission_rate: Mapped[float] = mapped_column(Float, default=0.0)
    working_hours: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    services = relationship("Service", secondary="master_services")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text)
    sku: Mapped[Optional[str]] = mapped_column(Text)
    stock: Mapped[float] = mapped_column(Float, default=0.0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    variants: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(Text)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    altegio_service_id: Mapped[Optional[str]] = mapped_column(Text)  # New field for Altegio mapping
    duration: Mapped[int] = mapped_column(Integer)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    master_id: Mapped[Optional[int]] = mapped_column(ForeignKey("masters.id"))
    appointment_time: Mapped[datetime] = mapped_column(DateTime)
    service_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="confirmed")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(Text, default="manual")
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_address: Mapped[Optional[str]] = mapped_column(Text)
    ttn: Mapped[Optional[str]] = mapped_column(Text)
    delivery_status: Mapped[str] = mapped_column(Text, default="pending")
    customer = relationship("Customer")
    master = relationship("Master")


class ActionLog(Base):
    __tablename__ = "action_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[Optional[int]] = mapped_column(ForeignKey("businesses.id"))
    user_id: Mapped[Optional[int]] = mapped_column(Integer) # Додано user_id
    action: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class ApiRequestLog(Base):
    __tablename__ = "api_request_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    endpoint: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class MonthlyPaymentLog(Base):
    __tablename__ = "monthly_payment_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    payment_date: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    receipt_url: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    business = relationship("Business")


class ChatLog(Base):
    __tablename__ = "chat_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    user_identifier: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_abandoned_cart: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class NPSReview(Base):
    __tablename__ = "nps_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    appointment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("appointments.id"))
    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    review_text: Mapped[Optional[str]] = mapped_column(Text)
    is_alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    appointment = relationship("Appointment")


class AppointmentConfirmation(Base):
    __tablename__ = "appointment_confirmations"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    confirmation_sent_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    no_show_alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomerSegment(Base):
    __tablename__ = "customer_segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), unique=True)
    rfm_segment: Mapped[str] = mapped_column(Text, default="new")  # vip, sleeping, regular, new
    last_calculated: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    total_visits: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    days_since_last_visit: Mapped[int] = mapped_column(Integer, default=0)


class GlobalPaymentSettings(Base):
    """Global payment settings for registration page"""
    __tablename__ = "global_payment_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    iban: Mapped[Optional[str]] = mapped_column(Text, default="UA363220010000026205345692520")
    card_number: Mapped[Optional[str]] = mapped_column(Text)
    receiver_name: Mapped[Optional[str]] = mapped_column(Text, default="SafeOrbit")
    qr_url: Mapped[Optional[str]] = mapped_column(Text)
    bank_name: Mapped[Optional[str]] = mapped_column(Text, default="Monobank")
    is_plan1_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_plan2_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan1_discount: Mapped[int] = mapped_column(Integer, default=0)
    plan2_discount: Mapped[int] = mapped_column(Integer, default=0)
    promo_code: Mapped[Optional[str]] = mapped_column(Text)
    promo_discount: Mapped[int] = mapped_column(Integer, default=0)
    promo_target_plan: Mapped[Optional[str]] = mapped_column(Text, default="all")
    promo_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    discount_duration_months: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

class SystemUpdate(Base):
    __tablename__ = "system_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    provider: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    token: Mapped[Optional[str]] = mapped_column(Text)
    ext_id: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    api_key: Mapped[str] = mapped_column(Text, unique=True) # Storing in plain text as per requirement
    name: Mapped[str] = mapped_column(Text, default="Default API Key")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    request_hash: Mapped[str] = mapped_column(Text)  # Hash of the request payload
    response_data: Mapped[Optional[str]] = mapped_column(Text)  # Stored JSON response
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime) # Keys should expire