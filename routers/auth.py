import os
import json
import shutil
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional
import logging

import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import SUPERADMIN_TG_BOT_TOKEN, SUPERADMIN_TG_CHAT_ID, UA_TZ
from database import get_db
from models import Business, CreemPayment, GlobalPaymentSettings, User
from utils.security import hash_password, verify_password
from services.demo_workspace import DEMO_SESSION_KEY, demo_workspaces
from services import creem
from utils.templates import login_html, render_template
from utils.auth import AttemptLimiter, normalize_username, login_limiter, registration_limiter, dummy_password_hash, save_document, remove_documents, ROOT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Authentication"])


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    settings = await db.get(GlobalPaymentSettings, 1)
    def amount(value):
        return f"{value:,}".replace(",", " ")
    payment = {
        "iban": (settings.iban if settings else None) or "Уточніть у адміністратора",
        "fop": (settings.receiver_name if settings else None) or "SafeOrbit",
        "bank": (settings.bank_name if settings else None) or "Уточніть у адміністратора",
        "edrpou": "",
    }
    d1 = max(0, min(100, (settings.plan1_discount if settings else 0) or 0))
    d2 = max(0, min(100, (settings.plan2_discount if settings else 0) or 0))
    prices = {
        "plan1_base": amount(round(8250 * (1 - d1 / 100))),
        "plan1_setup": amount(round(6750 * (1 - d1 / 100))),
        "plan2_base": amount(round(39750 * (1 - d2 / 100))),
        "plan2_support": amount(round(825 * (1 - d2 / 100))),
    }
    return HTMLResponse(render_template(
        "auth/register.html", payment=payment, prices=prices, global_discount=0,
        creem_plans=[plan for plan, discount in (("plan1", d1), ("plan2", d2)) if not discount and creem.charges(plan)],
        plan1_active=settings.is_plan1_active if settings else True,
        plan2_active=settings.is_plan2_active if settings else True,
        payment_us={
            "receiver": (settings.us_receiver_name if settings else None) or "Уточніть у адміністратора",
            "bank": (settings.us_bank_name if settings else None) or "Уточніть у адміністратора",
            "account": (settings.us_account_number if settings else None) or "Уточніть у адміністратора",
            "routing": (settings.us_routing_number if settings else None) or "Уточніть у адміністратора",
            "swift": (settings.us_swift if settings else None) or "Уточніть у адміністратора",
        },
        utm_source=request.query_params.get("utm_source", ""),
        utm_medium=request.query_params.get("utm_medium", ""),
        utm_campaign=request.query_params.get("utm_campaign", ""),
    ))


@router.post("/register")
async def register_post(request: Request, background_tasks: BackgroundTasks, name: str = Form(...), phone: str = Form(...), password: str = Form(...), type: str = Form(...), retail_subcategory: str = Form(None), payment_country: str = Form("ua"), plan_type: str = Form("plan1"), terms_accepted: str = Form(""), applied_promo: Optional[str] = Form(None), utm_source: Optional[str] = Form(None), utm_medium: Optional[str] = Form(None), utm_campaign: Optional[str] = Form(None), receipt: Optional[UploadFile] = File(None), nda_file: UploadFile = File(...), contract_file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    remote = request.client.host if request.client else "unknown"
    if not registration_limiter.allow(remote):
        return RedirectResponse("/register?error=rate", status_code=303)
    name, phone = name.strip(), normalize_username(phone)
    if not name or len(name) > 160 or not phone or len(phone) > 32 or len(password) < 8 or len(password) > 1024 or type not in {"barbershop", "clinic", "carwash", "spa", "retail", "restaurant", "other"}:
        return RedirectResponse("/register?error=fields", status_code=303)
    if terms_accepted != "yes":
        return RedirectResponse("/register?error=terms", status_code=303)
    existing = (await db.execute(select(User).where(User.username == phone))).scalar_one_or_none()
    if existing: return RedirectResponse("/register?error=exists", status_code=303)
    settings = await db.scalar(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))
    if plan_type not in {"plan1", "plan2"} or (settings and not getattr(settings, f"is_{plan_type}_active")):
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

    online = payment_country == "creem"
    charges = creem.charges(plan_type) if online else ()
    if online and (not charges or total_discount or applied_promo):
        return RedirectResponse("/register?error=plan", status_code=303)
    if not online and (not receipt or not receipt.filename):
        return RedirectResponse("/register?error=file", status_code=303)
    billing_country = payment_country if payment_country in ("ua", "us", "creem") else "ua"
    uploads = [(nda_file, "documents"), (contract_file, "documents")]
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
    f_nda, f_contract, *receipts = [path.relative_to(ROOT).as_posix() for path in saved]
    try:
        password_hash = await run_in_threadpool(hash_password, password)
    except Exception:
        await remove_documents(saved)
        raise
    nb = Business(name=name, type=type, retail_subcategory=retail_subcategory if type == 'retail' else None, billing_country=billing_country, plan_type=plan_type, contract_url=f"/{f_contract}", nda_url=f"/{f_nda}", is_active=False, payment_status="pending", receipt_url=f"/{receipts[0]}" if receipts else None, subscription_discount=total_discount, discount_ends_at=discount_ends_at, utm_source=utm_source, utm_medium=utm_medium, utm_campaign=utm_campaign)
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
    request.session.clear()
    request.session["pending_business_id"] = nb.id
    
    superadmin = (await db.execute(select(User).where(User.role == 'superadmin'))).scalars().first()
    bot_token = superadmin.tg_bot_token if superadmin and getattr(superadmin, 'tg_bot_token', None) else SUPERADMIN_TG_BOT_TOKEN
    chat_id = superadmin.tg_chat_id if superadmin and getattr(superadmin, 'tg_chat_id', None) else SUPERADMIN_TG_CHAT_ID

    if bot_token and chat_id:
        country_label = {"us": "США", "creem": "Creem (EUR)"}.get(billing_country, "Україна")
        if plan_type == "plan1":
            msg = f"🆕 Нова заявка на підключення!\nБізнес: {name}\nТелефон: {phone}\nКраїна оплати: {country_label}\nТариф: Базовий (8 250 грн/міс)"
        else:
            msg = f"🚀 🔥 УВАГА! НОВА VIP ЗАЯВКА!\nБізнес: {name}\nТелефон: {phone}\nКраїна оплати: {country_label}\nТариф: PRO (39 750 грн + 825 грн/міс) 💰\nОчікує перевірки!"
        background_tasks.add_task(notify_registration, bot_token, chat_id, msg)
            
    return RedirectResponse(f"/pending-activation/{nb.id}", status_code=303)


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
    outstanding = None
    if biz.billing_country == "creem" and status == "pending":
        outstanding = await db.scalar(select(CreemPayment).where(
            CreemPayment.business_id == id, CreemPayment.paid.is_(False),
        ).order_by(CreemPayment.recurring).limit(1))
    if status == "approved":
        title, description, label = "Ваш простір готовий.", "Підключення підтверджено. Увійдіть, щоб почати роботу.", "Активовано"
    elif status == "rejected":
        title, description, label = "Потрібно уточнити деталі.", "Адміністратор залишив повідомлення щодо вашої заявки.", "Потребує уточнення"
    else:
        title, description, label = "Дякуємо. Заявка вже у нас.", "Адміністратор перевірить підключення та активує ваш бізнес-простір.", "На перевірці"
    return HTMLResponse(render_template(
        "auth/pending.html", title=title, description=description, status_label=label,
        kicker="ПІДКЛЮЧЕННЯ SAFEORBIT",
        business_name=biz.name, message=biz.admin_message if status == "rejected" else None,
        checkout_business_id=id, outstanding=outstanding, checkout_error=payment_error == "1",
    ))


@router.post("/pending-activation/{id}/pay")
async def creem_pay(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("pending_business_id") != id:
        return RedirectResponse("/login", status_code=303)
    pending = f"/pending-activation/{id}"
    biz = await db.get(Business, id, with_for_update=True)
    if not biz or biz.billing_country != "creem" or biz.payment_status != "pending":
        return RedirectResponse(pending, status_code=303)
    if not creem.charges(biz.plan_type):
        return RedirectResponse(f"{pending}?payment_error=1", status_code=303)
    payments = (await db.scalars(select(CreemPayment).where(
        CreemPayment.business_id == id, CreemPayment.paid.is_(False),
    ).order_by(CreemPayment.recurring))).all()
    try:
        for payment in payments:
            if payment.checkout_id:
                checkout = await creem.api("GET", "checkouts", params={"checkout_id": payment.checkout_id})
                if creem.is_paid(checkout, payment.checkout_id, payment.id, payment.product_id, payment.cents):
                    payment.paid = True
                    continue
                if checkout.get("status") != "expired":
                    await db.commit()
                    if checkout.get("status") != "pending":
                        return RedirectResponse(f"{pending}?payment_error=1", status_code=303)
                    return RedirectResponse(creem.checkout_url(payment.checkout_url), status_code=303)
            product = await creem.api("GET", "products", params={"product_id": payment.product_id})
            expected_type = "recurring" if payment.recurring else "onetime"
            if (product.get("id") != payment.product_id or product.get("currency") != "EUR"
                    or product.get("price") != payment.cents or product.get("status") != "active"
                    or product.get("billing_type") != expected_type
                    or (payment.recurring and product.get("billing_period") != "every-month")):
                raise creem.CreemError("Product configuration differs from the advertised price")
            checkout = await creem.api("POST", "checkouts", json={
                "product_id": payment.product_id,
                "request_id": payment.id,
                "success_url": f"https://safeorbit.com.pl{pending}",
            })
            new_id = checkout.get("id")
            if not isinstance(new_id, str) or not new_id.startswith("ch_") or checkout.get("request_id") != payment.id:
                raise creem.CreemError("Invalid checkout reference")
            payment.checkout_id = new_id
            payment.checkout_url = creem.checkout_url(checkout.get("checkout_url"))
            await db.commit()
            return RedirectResponse(payment.checkout_url, status_code=303)
    except creem.CreemError:
        await db.rollback()
        logger.warning("Failed to confirm or open Creem checkout for business %s", id)
        return RedirectResponse(f"{pending}?payment_error=1", status_code=303)
    await db.commit()
    return RedirectResponse(pending, status_code=303)

@router.get("/", response_class=HTMLResponse)
async def public_home():
    return HTMLResponse(render_template("marketing/home.html"))


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
    request.session.clear()
    request.session[DEMO_SESSION_KEY] = key
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
    encoded = user.password if user else await run_in_threadpool(dummy_password_hash)
    valid = await run_in_threadpool(verify_password, password, encoded)
    if not user or not valid:
        return RedirectResponse("/login?error=invalid", status_code=303)
    if user.role == "owner" and user.business and not user.business.is_active:
        request.session.clear()
        request.session["pending_business_id"] = user.business_id
        return RedirectResponse(f"/pending-activation/{user.business_id}", status_code=303)
    if user.business_id and (not user.business or not user.business.is_active):
        return RedirectResponse("/login?error=inactive", status_code=303)
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/superadmin" if user.role == "superadmin" else "/admin", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)
