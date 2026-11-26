"""Private customer profile and merchant-issued voucher management."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from database import get_db
from models import Appointment, Business, Master
from models_platform import MarketplaceAvatar, MarketplaceClient, MarketplaceFavorite, MarketplaceListing, MarketplacePhoto, MarketplaceReview, MarketplaceVisit, MarketplaceVoucher
from routers.marketplace import CLIENT_PASSWORD_TAG, PREFIX, STATUSES, clean_photo, current_client, ip, password_tag
from routers.workspace import redirect, shell, uploaded, workspace_user
from services import marketplace as calendar, marketplace_vouchers as vouchers
from services.workspace_catalog import allowed_modules
from services.workspace_tools import ToolError, amount
from utils.auth import AttemptLimiter
from utils.security import hash_password, verify_password


router = APIRouter()
ACCOUNT = PREFIX + "/account"
MERCHANT = "/workspace/listing/vouchers"
SECTIONS = {"overview": "Огляд", "visits": "Мої візити", "reviews": "Відгуки", "favorites": "Обране",
            "vouchers": "Ваучери", "settings": "Налаштування"}
CLAIM_LIMIT = AttemptLimiter(limit=15, window=600)
PASSWORD_LIMIT = AttemptLimiter(limit=8, window=600)


async def account_screen(request, db, section, *, done="", error="", status=200):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    avatar = await db.scalar(select(MarketplaceAvatar.client_id).where(MarketplaceAvatar.client_id == client.id))
    rows, saved, wallet = [], [], []
    timestamp = calendar.now()
    if section in {"overview", "visits", "reviews"}:
        query = (select(Appointment, Business.name, Master.name, MarketplaceReview)
            .join(MarketplaceVisit, MarketplaceVisit.appointment_id == Appointment.id)
            .join(Business, Business.id == Appointment.business_id).outerjoin(Master, Master.id == Appointment.master_id)
            .outerjoin(MarketplaceReview, MarketplaceReview.appointment_id == Appointment.id)
            .where(MarketplaceVisit.client_id == client.id))
        if section == "reviews":
            query = query.where(MarketplaceReview.appointment_id.is_not(None)).order_by(MarketplaceReview.created_at.desc()).limit(100)
        elif section == "overview":
            upcoming = (Appointment.status == "confirmed") & (Appointment.appointment_time >= timestamp)
            query = query.order_by(
                upcoming.desc(),
                case((upcoming, Appointment.appointment_time)).asc(),
                Appointment.appointment_time.desc()).limit(4)
        else:
            query = query.order_by(Appointment.appointment_time.desc()).limit(150)
        rows = (await db.execute(query)).all()
    if section in {"overview", "favorites"}:
        photo = (select(func.min(MarketplacePhoto.id)).where(MarketplacePhoto.business_id == Business.id)
                 .correlate(Business).scalar_subquery())
        query = (select(Business.id, Business.name, MarketplaceListing.city, MarketplaceListing.address, photo.label("photo"))
            .join(MarketplaceFavorite, MarketplaceFavorite.business_id == Business.id)
            .join(MarketplaceListing, MarketplaceListing.business_id == Business.id)
            .where(MarketplaceFavorite.client_id == client.id, MarketplaceListing.published.is_(True), Business.is_active.is_(True))
            .order_by(Business.name).limit(4 if section == "overview" else 100))
        saved = (await db.execute(query)).all()
    if section == "vouchers":
        query = (select(MarketplaceVoucher, Business.name, Appointment.status, MarketplaceListing.published, Business.is_active)
            .join(Business, Business.id == MarketplaceVoucher.business_id)
            .join(MarketplaceListing, MarketplaceListing.business_id == Business.id)
            .outerjoin(Appointment, Appointment.id == MarketplaceVoucher.appointment_id)
            .where(MarketplaceVoucher.client_id == client.id).order_by(MarketplaceVoucher.id.desc()).limit(100))
        wallet = [(voucher, label, vouchers.status(voucher, visit), listed and active)
                  for voucher, label, visit, listed, active in (await db.execute(query)).all()]
    return shell("account", status=status, error=error, client=client, avatar=bool(avatar), section=section, sections=SECTIONS,
                 rows=rows, saved=saved, wallet=wallet, statuses=STATUSES, now=timestamp, done=done)


@router.get(ACCOUNT)
async def account(request: Request, done: str = "", db: AsyncSession = Depends(get_db)):
    return await account_screen(request, db, "overview", done=done)


@router.get(ACCOUNT + "/avatar")
async def account_avatar(request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    asset = await db.get(MarketplaceAvatar, client.id) if client else None
    if not asset:
        raise HTTPException(404)
    return Response(asset.content, media_type="image/jpeg")


@router.get(ACCOUNT + "/{section}")
async def account_section(section: str, request: Request, done: str = "", db: AsyncSession = Depends(get_db)):
    if section not in SECTIONS:
        raise HTTPException(404)
    return await account_screen(request, db, section, done=done)


@router.post(ACCOUNT)
@router.post(ACCOUNT + "/settings/profile")
async def update_profile(request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    form = await request.form()
    name = " ".join(str(form.get("name", "")).split())
    if not 1 <= len(name) <= 120:
        return await account_screen(request, db, "settings", error="Введіть ім’я до 120 символів.", status=422)
    client.name = name
    await db.commit()
    return redirect(ACCOUNT + "/settings?done=profile")


@router.post(ACCOUNT + "/settings/avatar")
async def save_avatar(request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    form = await request.form()
    if form.get("remove") == "yes":
        await db.execute(delete(MarketplaceAvatar).where(MarketplaceAvatar.client_id == client.id))
    else:
        try:
            _, _, raw = await uploaded(form, kinds={"jpg", "png"})
            photo = await run_in_threadpool(clean_photo, raw, (320, 320))
        except (ToolError, ValueError, OSError):
            return await account_screen(request, db, "settings", error="Завантажте фото JPG або PNG до 4 МБ.", status=422)
        asset = await db.get(MarketplaceAvatar, client.id)
        if asset:
            asset.content = photo
        else:
            db.add(MarketplaceAvatar(client_id=client.id, content=photo))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await account_screen(request, db, "settings", error="Фото вже оновлюється. Повторіть дію.", status=409)
    return redirect(ACCOUNT + "/settings?done=avatar")


@router.post(ACCOUNT + "/settings/password")
async def update_password(request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    if not PASSWORD_LIMIT.allow(str(client.id)):
        return await account_screen(request, db, "settings", error="Забагато спроб. Спробуйте пізніше.", status=429)
    form = await request.form()
    current, new, repeat = (str(form.get(key, "")) for key in ("current_password", "new_password", "repeat_password"))
    if new != repeat or new == current or not 8 <= len(new) <= 1024 or len(current) > 1024:
        return await account_screen(request, db, "settings", error="Повторіть новий пароль. Він має відрізнятися від поточного й містити від 8 символів.", status=422)
    previous = client.password
    if not await run_in_threadpool(verify_password, current, previous):
        return await account_screen(request, db, "settings", error="Поточний пароль неправильний.", status=422)
    updated = await run_in_threadpool(hash_password, new)
    changed = await db.execute(update(MarketplaceClient)
        .where(MarketplaceClient.id == client.id, MarketplaceClient.password == previous).values(password=updated))
    if not changed.rowcount:
        await db.rollback()
        return redirect(PREFIX + "/login")
    await db.commit()
    await db.refresh(client)
    request.session[CLIENT_PASSWORD_TAG] = password_tag(client)
    return redirect(ACCOUNT + "/settings?done=password")


@router.post(ACCOUNT + "/favorites/{business_id}/remove")
async def remove_saved(business_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    await db.execute(delete(MarketplaceFavorite).where(MarketplaceFavorite.client_id == client.id, MarketplaceFavorite.business_id == business_id))
    await db.commit()
    return redirect(ACCOUNT + "/favorites")


@router.post(ACCOUNT + "/vouchers/claim")
async def claim_voucher(request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    if not CLAIM_LIMIT.allow(ip(request)) or not CLAIM_LIMIT.allow("client:" + str(client.id)):
        return await account_screen(request, db, "vouchers", error="Забагато спроб. Спробуйте пізніше.", status=429)
    form = await request.form()
    code = vouchers.normalize_code(str(form.get("code", ""))[:42])
    assigned = None
    if code:
        result = await db.execute(update(MarketplaceVoucher).where(
            MarketplaceVoucher.digest == vouchers.code_digest(code), MarketplaceVoucher.client_id.is_(None),
            MarketplaceVoucher.revoked.is_(False), MarketplaceVoucher.expires_on >= calendar.now().date(),
            MarketplaceVoucher.business_id.in_(select(Business.id).where(Business.is_active.is_(True)))
        ).values(client_id=client.id).returning(MarketplaceVoucher.id))
        assigned = result.scalar_one_or_none()
        await db.commit()
    if assigned is None:
        return await account_screen(request, db, "vouchers", error="Перевірте код. Можливо, ваучер уже додано або строк його дії минув.", status=422)
    return redirect(ACCOUNT + "/vouchers?done=voucher")


async def check_merchant(db, user):
    if "directory" not in allowed_modules(user.business) or not await db.get(MarketplaceListing, user.business_id):
        raise HTTPException(404)


async def merchant_screen(db, user, *, code=None, error="", status=200):
    query = (select(MarketplaceVoucher, Appointment.status).outerjoin(Appointment, Appointment.id == MarketplaceVoucher.appointment_id)
             .where(MarketplaceVoucher.business_id == user.business_id).order_by(MarketplaceVoucher.id.desc()).limit(100))
    rows = [(item, vouchers.status(item, visit)) for item, visit in (await db.execute(query)).all()]
    today = calendar.now().date()
    return shell("merchant-vouchers", status=status, error=error, rows=rows, code=code, today=today.isoformat(),
                 latest=(today + timedelta(days=730)).isoformat())


@router.get(MERCHANT)
async def merchant_vouchers(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    await check_merchant(db, user)
    issued = request.session.pop("issued_marketplace_voucher", None)
    return await merchant_screen(db, user, code=issued[1] if issued and issued[0] == user.business_id else None)


@router.post(MERCHANT)
async def issue_voucher(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    await check_merchant(db, user)
    form = await request.form()
    label = str(form.get("title", "")).strip()
    try:
        expires = date.fromisoformat(str(form.get("ends", "")))
        today = calendar.now().date()
        value = int(amount(form.get("value"), minimum=1, maximum=50000) * 100)
        if not 1 <= len(label) <= 120 or not today <= expires <= today + timedelta(days=730):
            raise ValueError()
    except ValueError:
        return await merchant_screen(db, user, status=422, error="Перевірте назву, суму та строк дії ваучера.")
    code, digest, suffix = vouchers.new_code()
    db.add(MarketplaceVoucher(business_id=user.business_id, digest=digest, suffix=suffix, title=label, cents=value, expires_on=expires))
    await db.commit()
    request.session["issued_marketplace_voucher"] = [user.business_id, code]
    return redirect(MERCHANT)


@router.post(MERCHANT + "/{voucher_id}/revoke")
async def revoke_voucher(voucher_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    await check_merchant(db, user)
    await calendar.lock_calendar(db, user.business_id)
    item = await db.scalar(select(MarketplaceVoucher).where(MarketplaceVoucher.id == voucher_id, MarketplaceVoucher.business_id == user.business_id))
    if not item:
        raise HTTPException(404)
    visit = await db.get(Appointment, item.appointment_id) if item.appointment_id else None
    if visit and visit.status != "cancelled":
        return await merchant_screen(db, user, error="Ваучер уже застосовано до візиту.", status=409)
    item.revoked = True
    await db.commit()
    return redirect(MERCHANT)
