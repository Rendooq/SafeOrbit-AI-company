import os
import json
import shutil
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Annotated, Optional
import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import SUPERADMIN_TG_BOT_TOKEN, SUPERADMIN_TG_CHAT_ID, UA_TZ
from database import get_db
from models import ActivationDocument, Business, CreemPayment, GlobalPaymentSettings, User
from models_platform import CreemTermsAcceptance
from utils.security import hash_password, verify_password
from services.demo_workspace import DEMO_SESSION_KEY, demo_workspaces
from services import creem, marketing_funnel, phone_auth
from services.creem_billing import accepted_offer, record_paid_checkout
from services.workspace_catalog import INDUSTRIES, MODULES, PLAN_NAMES, allowed_modules, industry_plan
from utils.templates import login_html, render_template
from utils.auth import AttemptLimiter, normalize_username, login_limiter, registration_limiter, dummy_password_hash, read_document, save_document, remove_documents, ROOT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Authentication"])
PUBLIC_SITE = "https://safeorbit.com.pl"
SALON_PAGE = "/crm-dlia-saloniv"
PRICING_PAGE = "/taryfy"
BOOKING_TEMPLATE_PAGE = "/shablon-zhurnalu-zapysiv"
SCHEDULE_AUDIT_PAGE = "/rozbir-rozkladu"
SLOT_RECOVERY_PAGE = "/yak-zapovnyty-vilni-vikna-u-saloni"
CAMPAIGN_KEYS = ("utm_source", "utm_medium", "utm_campaign")
CAMPAIGN_SESSION_KEY = "marketing_campaign"


def campaign_attribution(request: Request | None) -> dict[str, str]:
    if request is None:
        return {}
    campaign = {}
    for key in CAMPAIGN_KEYS:
        value = request.query_params.get(key, "").strip()[:100]
        if value:
            campaign[key] = value
    session = request.scope.get("session", {})
    if campaign:
        session[CAMPAIGN_SESSION_KEY] = campaign
    return session.get(CAMPAIGN_SESSION_KEY, campaign)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    await marketing_funnel.capture_visit(request, db)
    settings = await db.get(GlobalPaymentSettings, 1)
    plan1_active = settings.is_plan1_active if settings else True
    plan2_active = settings.is_plan2_active if settings else True
    preferred = request.query_params.get("plan")
    selected_plan = "plan2" if plan2_active and (preferred == "plan2" or not plan1_active) else "plan1"
    industries = [
        (key, industry, [MODULES[module].label for module in industry.modules], creem.advertised(industry.plan),
         PLAN_NAMES[industry.plan],
         (f"/terms/subscription/{industry.plan}" if creem.offer_version(industry.plan)
          else creem.agreement_path(industry.plan)))
        for key, industry in INDUSTRIES.items()
    ]
    return HTMLResponse(render_template(
        "auth/register.html",
        plan1_active=plan1_active, plan2_active=plan2_active, selected_plan=selected_plan,
        industries=industries, selected_industry=request.query_params.get("industry", "barbershop"),
        standard_prices={plan: creem.advertised(plan) for plan in ("plan1", "plan2")},
        sms_required=phone_auth.enabled(),
        sms_pending=phone_auth.pending(request, phone_auth.SIGNUP_BUSINESS) if "session" in request.scope else None,
        **campaign_attribution(request),
    ))


@router.get("/register/phone")
async def registration_phone():
    if not phone_auth.enabled():
        return RedirectResponse("/register", status_code=303)
    return HTMLResponse(render_template("auth/sms.html", mode="register-phone"))


@router.post("/register/phone")
async def send_registration_code(request: Request, phone: str = Form(""), db: AsyncSession = Depends(get_db)):
    status, message = 200, "Код надіслано. Він дійсний 8 хвилин."
    try:
        await phone_auth.issue(request, db, phone_auth.SIGNUP_BUSINESS, phone[:40])
    except phone_auth.ChallengeError as error:
        status, message = error.status, str(error)
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"message": message}, status_code=status)
    if status == 200:
        return RedirectResponse("/register", status_code=303)
    return HTMLResponse(render_template("auth/sms.html", mode="register-phone", error=message), status_code=status)


@router.post("/register")
async def register_post(request: Request, background_tasks: BackgroundTasks, name: str = Form(...), phone: str = Form(...), password: str = Form(...), type: str = Form(...), retail_subcategory: str = Form(None), payment_country: str = Form("ua"), plan_type: str = Form("plan1"), terms_accepted: str = Form(""), applied_promo: Optional[str] = Form(None), utm_source: Optional[str] = Form(None), utm_medium: Optional[str] = Form(None), utm_campaign: Optional[str] = Form(None), receipt: Optional[UploadFile] = File(None), nda_file: Optional[UploadFile] = File(None), contract_file: Optional[UploadFile] = File(None), db: AsyncSession = Depends(get_db), registration_flow: Annotated[str, Form()] = "", sms_code: Annotated[str, Form()] = ""):
    remote = request.client.host if request.client else "unknown"
    if not registration_limiter.allow(remote):
        return RedirectResponse("/register?error=rate", status_code=303)
    name, phone = name.strip(), normalize_username(phone)
    sms_required = phone_auth.enabled()
    phone = phone_auth.normalize_phone(phone) if sms_required else phone
    if not name or len(name) > 160 or not re.fullmatch(r"\+?[0-9]{7,15}", phone) or len(password) < 8 or len(password) > 1024 or type not in INDUSTRIES:
        return RedirectResponse("/register?error=fields", status_code=303)
    if terms_accepted != "yes":
        return RedirectResponse("/register?error=terms", status_code=303)
    if not sms_required and await db.scalar(select(User.id).where(User.username == phone)):
        return RedirectResponse("/register?error=exists", status_code=303)
    settings = await db.scalar(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))
    if plan_type not in creem.PLAN_PRICES:
        return RedirectResponse("/register?error=plan", status_code=303)
    if registration_flow == "access":
        plan_type = industry_plan(type, plan_type)
    if ((registration_flow != "access" and plan_type not in {"plan1", "plan2"})
            or (settings and plan_type in {"plan1", "plan2"} and not getattr(settings, f"is_{plan_type}_active"))):
        return RedirectResponse("/register?error=plan", status_code=303)
    total_discount = 0
    promo_duration = 0
    promo_applied = False
    if settings:
        total_discount += getattr(settings, 'plan1_discount', 0) if plan_type == 'plan1' else getattr(settings, 'plan2_discount', 0)
        if applied_promo and settings.promo_code:
            try:
                if settings.promo_code.strip().startswith('['):
                    promos = json.loads(settings.promo_code)
                else:
                    promos = [{
                        "code": settings.promo_code,
                        "discount": getattr(settings, 'promo_discount', 0),
                        "plan": getattr(settings, 'promo_target_plan', 'all'),
                        "expires": settings.promo_expires_at.strftime('%Y-%m-%d') if getattr(settings, 'promo_expires_at', None) else "",
                        "duration": getattr(settings, 'discount_duration_months', 0)
                    }]
            except:
                promos = []
            for p in promos:
                if str(p.get('code', '')).upper() == applied_promo.strip().upper():
                    is_valid = True
                    if p.get('expires') and datetime.now(UA_TZ).replace(tzinfo=None) > datetime.strptime(p['expires'], "%Y-%m-%d"):
                        is_valid = False
                    if p.get('plan', 'all') not in ['all', plan_type]:
                        is_valid = False
                    if is_valid:
                        total_discount += int(p.get('discount', 0))
                        promo_duration = int(p.get('duration', 0))
                        promo_applied = True
                    break
    
    total_discount = max(0, min(100, total_discount))
    discount_ends_at = None
    if total_discount > 0:
        if promo_applied:
            if promo_duration > 0:
                discount_ends_at = datetime.now(UA_TZ).replace(tzinfo=None) + timedelta(days=30 * promo_duration)
        elif settings and getattr(settings, 'discount_duration_months', 0) > 0:
            discount_ends_at = datetime.now(UA_TZ).replace(tzinfo=None) + timedelta(days=30 * settings.discount_duration_months)

    free_signup = registration_flow == "access"
    online = free_signup or payment_country == "creem"
    charges = creem.charges(plan_type) if online else ()
    if online and not free_signup and (not charges or total_discount or applied_promo):
        return RedirectResponse("/register?error=plan", status_code=303)
    if not free_signup and (not nda_file or not contract_file):
        return RedirectResponse("/register?error=file", status_code=303)
    if not online and (not receipt or not receipt.filename):
        return RedirectResponse("/register?error=file", status_code=303)
    if sms_required:
        try:
            await phone_auth.consume(request, db, phone_auth.SIGNUP_BUSINESS, sms_code.strip(), expected_phone=phone)
        except phone_auth.ChallengeError:
            return RedirectResponse("/register?error=sms", status_code=303)
        aliases = {phone, phone[1:]}
        if phone.startswith("+380"):
            aliases.add(phone[3:])
        if await db.scalar(select(User.id).where(User.username.in_(aliases)).limit(1)):
            return RedirectResponse("/register?error=exists", status_code=303)
    billing_country = "creem" if online else ("us" if payment_country == "us" else "ua")
    uploads = [] if free_signup else [(nda_file, "documents"), (contract_file, "documents")]
    if not online:
        uploads.append((receipt, "receipts"))
    saved = []
    try:
        for upload, directory in uploads:
            saved.append(await save_document(upload, directory))
    except ValueError:
        await remove_documents(saved)
        return RedirectResponse("/register?error=file", status_code=303)
    except Exception:
        await remove_documents(saved)
        raise
    links = [f"/{path.relative_to(ROOT).as_posix()}" for path in saved]
    nda_url, contract_url, receipt_url = (links + [None] * 3)[:3]
    try:
        password_hash = await run_in_threadpool(hash_password, password)
    except Exception:
        await remove_documents(saved)
        raise
    nb = Business(name=name, type=type, retail_subcategory=retail_subcategory if type == 'retail' else None, billing_country=billing_country, plan_type=plan_type, contract_url=contract_url, nda_url=nda_url, is_active=False, payment_status="pending", receipt_url=receipt_url, subscription_discount=0 if free_signup else total_discount, discount_ends_at=None if free_signup else discount_ends_at, utm_source=utm_source, utm_medium=utm_medium, utm_campaign=utm_campaign)
    try:
        db.add(nb)
        await db.flush()
        nu = User(username=phone, password=password_hash, role="owner", business_id=nb.id)
        db.add(nu)
        db.add_all(CreemPayment(id=uuid4().hex, business_id=nb.id, product_id=charge.product_id,
                               cents=charge.cents, recurring=charge.recurring) for charge in charges)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        await remove_documents(saved)
        return RedirectResponse("/register?error=exists", status_code=303)
    except Exception:
        await db.rollback()
        await remove_documents(saved)
        raise
    business_id = nb.id
    await marketing_funnel.link_registration(request, business_id, db)
    request.session.clear()
    request.session["pending_business_id"] = business_id
    
    superadmin = (await db.execute(select(User).where(User.role == 'superadmin'))).scalars().first()
    bot_token = superadmin.tg_bot_token if superadmin and getattr(superadmin, 'tg_bot_token', None) else SUPERADMIN_TG_BOT_TOKEN
    chat_id = superadmin.tg_chat_id if superadmin and getattr(superadmin, 'tg_chat_id', None) else SUPERADMIN_TG_CHAT_ID

    if bot_token and chat_id:
        country_label = {"us": "США", "creem": "Creem (EUR)"}.get(billing_country, "Україна")
        if online:
            plan_name = PLAN_NAMES.get(plan_type, plan_type)
            (_, setup), (_, monthly) = creem.PLAN_PRICES[plan_type]
            msg = f"Нова заявка SafeOrbit\nБізнес: {name}\nТелефон: {phone}\n{plan_name} · Creem\nПідписка: €{monthly / 100:.2f}/міс"
            if setup:
                msg += f"\nПідключення: €{setup / 100:.2f}"
        elif plan_type == "plan1":
            msg = f"🆕 Нова заявка на підключення!\nБізнес: {name}\nТелефон: {phone}\nКраїна оплати: {country_label}\nТариф: Базовий (8 250 грн/міс)"
        else:
            msg = f"🚀 🔥 УВАГА! НОВА VIP ЗАЯВКА!\nБізнес: {name}\nТелефон: {phone}\nКраїна оплати: {country_label}\nТариф: PRO (39 750 грн + 825 грн/міс) 💰\nОчікує перевірки!"
        background_tasks.add_task(notify_registration, bot_token, chat_id, msg)
            
    return RedirectResponse(f"/pending-activation/{business_id}", status_code=303)


async def notify_registration(bot_token, chat_id, message):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": message})
    except httpx.HTTPError:
        logger.warning("Registration notification failed")


@router.get("/pending-activation/{id}", response_class=HTMLResponse)
async def pending_activation_page(id: int, request: Request, db: AsyncSession = Depends(get_db), payment_error: str = ""):
    # Status links must not expose other tenants via sequential business IDs.
    if request.session.get("pending_business_id") != id:
        return RedirectResponse("/login", status_code=303)
    biz = await db.get(Business, id)
    if not biz:
        return RedirectResponse("/login", status_code=303)
    status = biz.payment_status or "pending"
    limited = biz.billing_country == "creem" and status == "pending"
    acceptance = await accepted_offer(db, biz) if limited else None
    offer_version = creem.offer_version(biz.plan_type) if limited else ""
    online_offer = bool(offer_version or acceptance)
    payments = []
    available = ()
    if limited:
        payments = (await db.scalars(select(CreemPayment).where(
            CreemPayment.business_id == id,
        ).order_by(CreemPayment.recurring))).all()
        available = creem.charges(biz.plan_type)
    prices = payments or available or (creem.advertised(biz.plan_type) if limited else ())
    setup_required = (any(not row.recurring for row in prices) if prices else biz.plan_type == "plan2")
    outstanding = next((row for row in payments if not row.paid), None)
    if not payments and available:
        outstanding = available[0]
    if status == "approved":
        title, description, label = "Ваш простір готовий.", "Підключення підтверджено. Увійдіть, щоб почати роботу.", "Активовано"
    elif status == "expired":
        title, description, label = "Дію підписки призупинено.", "Поновіть оплату за посиланням Creem з вашого листа про підписку.", "Потрібне поновлення"
    elif status == "rejected":
        title, description, label = "Потрібно уточнити деталі.", "Адміністратор залишив повідомлення щодо вашої заявки.", "Потребує уточнення"
    elif limited and (outstanding or not payments):
        title, label = "Ваш акаунт створено.", "Обмежений доступ"
        description = ("Оплатіть підключення та підписку, щоб відкрити робочий простір SafeOrbit."
                       if setup_required else "Оформіть щомісячну підписку, щоб відкрити робочий простір SafeOrbit.")
    elif limited and online_offer:
        title, description, label = "Перевіряємо підписку.", "Creem підтверджує термін оплаченого доступу.", "На перевірці"
    else:
        title, description, label = "Дякуємо. Заявка вже у нас.", "Адміністратор перевірить підключення та активує ваш бізнес-простір.", "На перевірці"
    return HTMLResponse(render_template(
        "auth/pending.html", title=title, description=description, status_label=label,
        kicker="ПІДКЛЮЧЕННЯ SAFEORBIT",
        business_name=biz.name, message=biz.admin_message if status == "rejected" else None,
        checkout_business_id=id, outstanding=outstanding, checkout_error=payment_error == "1",
        limited=limited, payment_available=bool(available) or (bool(payments) and creem.enabled()), prices=prices,
        setup_required=setup_required, setup_paid=not setup_required or any(row.paid and not row.recurring for row in payments),
        monthly_paid=any(row.paid and row.recurring for row in payments),
        plan_name=PLAN_NAMES.get(biz.plan_type, "Business"),
        plan_modules=[MODULES[module].label for module in allowed_modules(biz)[:8]],
        contract_path=("/static/contract_plan1.pdf" if biz.plan_type == "plan1" and setup_required else creem.agreement_path(biz.plan_type)),
        documents_ready=bool(biz.nda_url and biz.contract_url), document_error=payment_error == "documents",
        online_offer=online_offer, offer_version=offer_version, offer_accepted=bool(acceptance),
        offer_error=payment_error == "terms", offer_path=f"/terms/subscription/{biz.plan_type}",
    ))


@router.get("/terms/subscription/{plan}", response_class=HTMLResponse)
async def online_subscription_terms(plan: str):
    version = creem.offer_version(plan)
    if not version:
        raise HTTPException(404)
    return HTMLResponse(render_template("auth/creem-offer.html", plan_name=PLAN_NAMES[plan], version=version,
                                        monthly=creem.advertised(plan)[0].cents))


@router.post("/pending-activation/{id}/documents")
async def submit_access_documents(id: int, request: Request, nda: UploadFile = File(...),
                                  contract: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if request.session.get("pending_business_id") != id:
        return RedirectResponse("/login", status_code=303)
    pending = f"/pending-activation/{id}"
    biz = await db.get(Business, id, with_for_update=True)
    if not biz or biz.billing_country != "creem" or biz.payment_status != "pending" or (biz.nda_url and biz.contract_url):
        return RedirectResponse(pending, status_code=303)
    try:
        documents = []
        for upload in (nda, contract):
            content, extension = await read_document(upload)
            url = f"/static/uploads/documents/{uuid4().hex}{extension}"
            documents.append(ActivationDocument(url=url, business_id=id, content=content))
    except ValueError:
        return RedirectResponse(f"{pending}?payment_error=documents", status_code=303)
    biz.nda_url, biz.contract_url = (document.url for document in documents)
    db.add_all(documents)
    await db.commit()
    return RedirectResponse(pending, status_code=303)


@router.post("/pending-activation/{id}/pay")
async def creem_pay(id: int, request: Request, db: AsyncSession = Depends(get_db),
                    verify_only: Annotated[bool, Form()] = False, accept_offer: Annotated[str, Form()] = ""):
    def respond(location: str):
        if request.headers.get("accept") == "application/json":
            return JSONResponse({"location": location})
        return RedirectResponse(location, status_code=303)

    if request.session.get("pending_business_id") != id:
        return respond("/login")
    pending = f"/pending-activation/{id}"
    biz = await db.get(Business, id, with_for_update=True)
    if not biz or biz.billing_country != "creem" or biz.payment_status != "pending":
        return respond(pending)
    payments = (await db.scalars(select(CreemPayment).where(
        CreemPayment.business_id == id,
    ).order_by(CreemPayment.recurring))).all()
    charges = creem.charges(biz.plan_type)
    if not charges and not (payments and creem.enabled()):
        return respond(f"{pending}?payment_error=1")
    version = creem.offer_version(biz.plan_type)
    if not verify_only and version and not await accepted_offer(db, biz):
        if accept_offer != version:
            return respond(f"{pending}?payment_error=terms")
        db.add(CreemTermsAcceptance(business_id=id, plan_type=biz.plan_type, version=version))
    if not payments and not verify_only:
        payments = [CreemPayment(id=uuid4().hex, business_id=id, product_id=charge.product_id,
                                 cents=charge.cents, recurring=charge.recurring) for charge in charges]
        db.add_all(payments)
    try:
        for payment in payments:
            if payment.paid:
                continue
            if payment.checkout_id:
                checkout = await creem.api("GET", "checkouts", params={"checkout_id": payment.checkout_id})
                if creem.is_paid(checkout, payment.checkout_id, payment.product_id, payment.cents):
                    await record_paid_checkout(db, biz, payment, checkout)
                    if verify_only:
                        break
                    continue
                if verify_only:
                    break
                if checkout.get("status") != "expired":
                    await db.commit()
                    if checkout.get("status") != "pending":
                        return respond(f"{pending}?payment_error=1")
                    return respond(creem.checkout_url(payment.checkout_url))
            if verify_only:
                break
            product = await creem.get_product(payment.product_id)
            expected_type = "recurring" if payment.recurring else "onetime"
            if (product.get("id") != payment.product_id or product.get("currency") != "EUR"
                    or product.get("price") != payment.cents or product.get("status") != "active"
                    or product.get("billing_type") != expected_type
                    or (payment.recurring and product.get("billing_period") != "every-month")):
                raise creem.CreemError("Product configuration differs from the advertised price")
            checkout = await creem.api("POST", "checkouts", json={
                "product_id": payment.product_id,
                "request_id": payment.id,
                "success_url": f"{PUBLIC_SITE}{pending}?checkout_return=1",
            })
            new_id = checkout.get("id")
            if not isinstance(new_id, str) or not new_id.startswith("ch_"):
                raise creem.CreemError("Creem did not return a checkout session ID")
            payment.checkout_id = new_id
            payment.checkout_url = creem.checkout_url(checkout.get("checkout_url"))
            await db.commit()
            return respond(payment.checkout_url)
    except creem.CreemError as exc:
        await db.rollback()
        logger.warning("Failed to confirm or open Creem checkout for business %s: %s", id, exc)
        return respond(f"{pending}?payment_error=1")
    await db.commit()
    return respond(pending)

@router.get("/", response_class=HTMLResponse)
async def public_home(request: Request = None, db: AsyncSession = Depends(get_db)):
    await marketing_funnel.capture_visit(request, db)
    campaign_attribution(request)
    return HTMLResponse(render_template(
        "marketing/home.html", public_site=PUBLIC_SITE, plans=creem.PLAN_PRICES,
        industries=[(key, INDUSTRIES[key], [MODULES[m].label for m in INDUSTRIES[key].modules[:3]])
                    for key in ("retail", "construction", "restaurant", "tenders", "furniture", "print", "cars", "family", "other")],
        site_verification=os.getenv("GOOGLE_SITE_VERIFICATION", "").strip(),
    ))


@router.get(SALON_PAGE, response_class=HTMLResponse)
async def salon_landing(request: Request = None, db: AsyncSession = Depends(get_db)):
    await marketing_funnel.capture_visit(request, db)
    campaign_attribution(request)
    return HTMLResponse(render_template(
        "marketing/salons.html", canonical=PUBLIC_SITE + SALON_PAGE, public_site=PUBLIC_SITE,
    ))


@router.get(PRICING_PAGE, response_class=HTMLResponse)
async def public_pricing(db: AsyncSession = Depends(get_db), request: Request = None):
    await marketing_funnel.capture_visit(request, db)
    settings = await db.get(GlobalPaymentSettings, 1)
    active_plans = {plan for plan in ("plan1", "plan2")
                    if settings is None or getattr(settings, f"is_{plan}_active")}
    industry_options = {
        plan: [(key, industry.label) for key, industry in INDUSTRIES.items() if industry.plan == plan]
        for plan in creem.ONLINE_TERMS_PLANS
    }
    active_plans.update(plan for plan in industry_options if creem.charges(plan))
    online_plans = {plan for plan in industry_options if creem.offer_version(plan)}
    agreements = {
        plan: f"/terms/subscription/{plan}" if plan in online_plans else creem.agreement_path(plan)
        for plan in PLAN_NAMES
    }
    return HTMLResponse(render_template(
        "marketing/pricing.html", canonical=PUBLIC_SITE + PRICING_PAGE,
        plans=creem.PLAN_PRICES, plan_names=PLAN_NAMES, active_plans=active_plans,
        industry_options=industry_options, online_plans=online_plans, agreements=agreements,
        has_campaign=bool(campaign_attribution(request)),
    ))


@router.get(BOOKING_TEMPLATE_PAGE, response_class=HTMLResponse)
async def public_booking_template(request: Request, db: AsyncSession = Depends(get_db)):
    await marketing_funnel.capture_visit(request, db)
    campaign_attribution(request)
    return HTMLResponse(render_template(
        "marketing/booking-template.html", canonical=PUBLIC_SITE + BOOKING_TEMPLATE_PAGE, public_site=PUBLIC_SITE,
    ))


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return f"User-agent: *\nAllow: /\nSitemap: {PUBLIC_SITE}/sitemap.xml\n"


@router.get(SCHEDULE_AUDIT_PAGE, response_class=HTMLResponse)
async def public_schedule_audit(request: Request, db: AsyncSession = Depends(get_db)):
    await marketing_funnel.capture_visit(request, db)
    campaign_attribution(request)
    return HTMLResponse(render_template(
        "marketing/schedule-audit.html", canonical=PUBLIC_SITE + SCHEDULE_AUDIT_PAGE,
    ))


@router.get(SLOT_RECOVERY_PAGE, response_class=HTMLResponse)
async def public_slot_recovery(request: Request, db: AsyncSession = Depends(get_db)):
    await marketing_funnel.capture_visit(request, db)
    campaign_attribution(request)
    return HTMLResponse(render_template(
        "platform/slot-recovery.html", canonical=PUBLIC_SITE + SLOT_RECOVERY_PAGE, public_site=PUBLIC_SITE,
    ))


@router.get("/sitemap.xml")
async def sitemap_xml():
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'<url><loc>{PUBLIC_SITE}/</loc></url>'
        f'<url><loc>{PUBLIC_SITE}{SALON_PAGE}</loc></url>'
        f'<url><loc>{PUBLIC_SITE}{PRICING_PAGE}</loc></url>'
        f'<url><loc>{PUBLIC_SITE}/maistry</loc></url>'
        f'<url><loc>{PUBLIC_SITE}{BOOKING_TEMPLATE_PAGE}</loc></url>'
        f'<url><loc>{PUBLIC_SITE}{SCHEDULE_AUDIT_PAGE}</loc></url>'
        f'<url><loc>{PUBLIC_SITE}{SLOT_RECOVERY_PAGE}</loc></url></urlset>',
        media_type="application/xml",
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(login_html())


demo_limiter = AttemptLimiter(limit=6)


@router.get("/login-demo")
async def login_demo(request: Request):
    existing = request.session.get(DEMO_SESSION_KEY)
    remote = request.client.host if request.client else "unknown"
    if not existing and not demo_limiter.allow(remote):
        raise HTTPException(429, "Забагато спроб відкрити демо. Спробуйте за хвилину.")
    key = await demo_workspaces.start(existing)
    campaign = campaign_attribution(request)
    visit = request.session.get(marketing_funnel.VISIT_SESSION_KEY)
    request.session.clear()
    request.session[DEMO_SESSION_KEY] = key
    if campaign:
        request.session[CAMPAIGN_SESSION_KEY] = campaign
    if visit:
        request.session[marketing_funnel.VISIT_SESSION_KEY] = visit
    return RedirectResponse("/admin", status_code=303)


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    remote = request.client.host if request.client else "unknown"
    if not login_limiter.allow(remote):
        return RedirectResponse("/login?error=rate", status_code=303)
    username = normalize_username(username)
    if len(username) > 200 or len(password) > 1024:
        return RedirectResponse("/login?error=invalid", status_code=303)
    result = await db.execute(select(User).options(joinedload(User.business)).where(User.username == username))
    user = result.scalar_one_or_none()
    phone = phone_auth.normalize_phone(username)
    if not user and phone and username != phone:
        user = await db.scalar(select(User).options(joinedload(User.business)).where(User.username == phone))
    encoded = user.password if user else await run_in_threadpool(dummy_password_hash)
    valid = await run_in_threadpool(verify_password, password, encoded)
    if not user or not valid:
        return RedirectResponse("/login?error=invalid", status_code=303)
    if phone and phone_auth.enabled():
        identifier = user.id
        await db.rollback()
        try:
            await phone_auth.issue(request, db, phone_auth.SIGNIN_BUSINESS, phone, identity=identifier)
        except phone_auth.ChallengeError as error:
            return HTMLResponse(render_template("auth/sms.html", mode="login-error", error=str(error)), status_code=error.status)
        request.session.pop("user_id", None)
        request.session.pop("pending_business_id", None)
        return RedirectResponse("/login/verify", status_code=303)
    return finish_sign_in(request, user)


@router.get("/login/verify")
async def verification_page(request: Request):
    if not phone_auth.pending(request, phone_auth.SIGNIN_BUSINESS):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(render_template("auth/sms.html", mode="login"))


@router.post("/login/verify")
async def verify_sign_in(request: Request, code: str = Form(""), db: AsyncSession = Depends(get_db)):
    try:
        challenge = await phone_auth.consume(request, db, phone_auth.SIGNIN_BUSINESS, code.strip())
    except phone_auth.ChallengeError as error:
        return HTMLResponse(render_template("auth/sms.html", mode="login", error=str(error)), status_code=error.status)
    user = await db.scalar(select(User).options(joinedload(User.business)).where(User.id == challenge["identity"]))
    if not user or phone_auth.normalize_phone(user.username) != challenge["phone"]:
        return RedirectResponse("/login?error=invalid", status_code=303)
    return finish_sign_in(request, user)


def finish_sign_in(request, user):
    if user.role == "owner" and user.business and not user.business.is_active:
        request.session.clear()
        request.session["pending_business_id"] = user.business_id
        return RedirectResponse(f"/pending-activation/{user.business_id}", status_code=303)
    if user.business_id and (not user.business or not user.business.is_active):
        return RedirectResponse("/login?error=inactive", status_code=303)
    request.session.clear()
    request.session["user_id"] = user.id
    if user.role == "superadmin":
        return RedirectResponse("/superadmin", status_code=303)
    if user.role == "owner" and user.business and (
        user.business.plan_type in {"commerce", "production", "custom"}
        or user.business.type in {"cars", "family", "construction", "tenders", "furniture", "print"}
    ):
        return RedirectResponse("/workspace", status_code=303)
    return RedirectResponse("/admin", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)
