"""Public directory and authenticated customer booking."""
import io
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from database import get_db
from models import ActionLog, Appointment, Business, Customer, Master, Service
from models_platform import (MarketplaceClient, MarketplaceFavorite, MarketplaceListing, MarketplaceListingCategory,
                             MarketplacePhoto, MarketplaceReview, MarketplaceVisit)
from routers.workspace import redirect, shell, uploaded, workspace_user
from services.workspace_tools import ToolError
from services import marketplace as calendar
from services.notifications import send_new_appointment_notifications
from services import phone_auth
from services.workspace_catalog import allowed_modules
from utils.auth import AttemptLimiter, dummy_password_hash
from utils.security import hash_password, verify_password


router = APIRouter()
PREFIX = "/maistry"
CLIENT = "marketplace_client_id"
DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")
LOGIN_LIMIT = AttemptLimiter(limit=12, window=300)
BOOK_LIMIT = AttemptLimiter(limit=12, window=120)
STATUSES = {"confirmed": "Підтверджено", "completed": "Відбувся", "cancelled": "Скасовано", "no_show": "Не відбувся"}
CATEGORIES = {
    "barber": "Барбершоп",
    "hair": "Перукарня",
    "nails": "Манікюр і педикюр",
    "beauty": "Косметологія",
    "brows": "Брови та вії",
    "massage": "Масаж",
    "spa": "SPA",
}


def ip(request):
    return request.client.host if request.client else "unknown"


async def current_client(request, db):
    uid = request.session.get(CLIENT)
    return await db.get(MarketplaceClient, uid) if type(uid) is int else None


async def get_listing(db, business_id):
    found = (await db.execute(select(Business, MarketplaceListing).join(
        MarketplaceListing, MarketplaceListing.business_id == Business.id
    ).where(Business.id == business_id, Business.is_active.is_(True), MarketplaceListing.published.is_(True)))).first()
    if not found:
        raise HTTPException(404, "Профіль закладу недоступний.")
    return found


@router.get(PREFIX)
async def directory(request: Request, city: str = "", q: str = "", max_price: str = "", day: str = "",
                    category: str = "", sort: str = "", saved: bool = False, page: int = 1, db: AsyncSession = Depends(get_db)):
    city, q, page = city.strip()[:100], q.strip()[:100], max(1, min(page, 1000))
    if max_price and not re.fullmatch(r"[0-9]{1,6}", max_price):
        raise HTTPException(422, "Вкажіть коректну максимальну ціну.")
    max_price = int(max_price or "0")
    category = category if category in CATEGORIES else ""
    client = await current_client(request, db)
    if saved and not client:
        return redirect(PREFIX + "/login")
    favorites = set((await db.scalars(select(MarketplaceFavorite.business_id)
        .where(MarketplaceFavorite.client_id == client.id))).all()) if client else set()
    qfold = q.casefold()
    selected_day = calendar.date_in_range(day) if day else None
    if day and not selected_day:
        raise HTTPException(422, "Виберіть дату в межах наступних 60 днів.")
    ratings = (select(Appointment.business_id.label("bid"), func.avg(MarketplaceReview.rating).label("rating"),
                     func.count(MarketplaceReview.rating).label("review_count"))
        .join(MarketplaceReview, MarketplaceReview.appointment_id == Appointment.id)
        .where(Appointment.status == "completed").group_by(Appointment.business_id).subquery())
    minimum = (select(func.min(Service.price)).where(Service.business_id == Business.id, Service.price >= 0,
                                                       Service.duration > 0, Service.duration <= 720).scalar_subquery())
    photo_id = select(func.min(MarketplacePhoto.id)).where(MarketplacePhoto.business_id == Business.id).scalar_subquery()
    statement = (select(Business.id, Business.name, MarketplaceListing.city, MarketplaceListing.address,
                       MarketplaceListing.description, minimum.label("price"), ratings.c.rating, ratings.c.review_count,
                       photo_id.label("photo_id"))
                 .join(MarketplaceListing, MarketplaceListing.business_id == Business.id)
                 .outerjoin(ratings, ratings.c.bid == Business.id)
                 .where(Business.is_active.is_(True), MarketplaceListing.published.is_(True)))
    # SQLite's LOWER handles only ASCII. Normalize the short searchable strings in Python.
    if max_price > 0:
        statement = statement.where(minimum <= max_price)
    if category:
        assigned = exists().where(MarketplaceListingCategory.business_id == Business.id)
        matching = exists().where(MarketplaceListingCategory.business_id == Business.id,
                                   MarketplaceListingCategory.category == category)
        inferred = (Business.type == {"barber": "barbershop", "spa": "spa"}.get(category, "")
                    ) & ~assigned
        statement = statement.where(matching | inferred)
    if saved:
        statement = statement.where(Business.id.in_(favorites))
    if sort == "rating":
        statement = statement.order_by(func.coalesce(ratings.c.rating, 0).desc(), func.coalesce(ratings.c.review_count, 0).desc())
    elif sort == "price":
        statement = statement.order_by(minimum.asc().nulls_last())
    iter_rows = await db.stream(statement.order_by(Business.name, Business.id))
    results, skipped = [], 0
    async for row in iter_rows:
        if city and city.casefold() not in row.city.casefold():
            continue
        services = team = mapping = None
        if qfold or selected_day:
            services, team, mapping = await calendar.services_and_team(db, row.id)
        if qfold and not any(qfold in value.casefold() for value in
                            [row.name, row.description, *[s.name for s in services], *[m.name for m in team]]):
            continue
        if selected_day:
            listing = await db.get(MarketplaceListing, row.id)
            suitable = [s for s in services if (not max_price or s.price <= max_price)]
            if qfold and any(qfold in s.name.casefold() for s in suitable):
                suitable = [s for s in suitable if qfold in s.name.casefold()]
            eligibles = [m for m in team if qfold in m.name.casefold()] if qfold else team
            eligibles = eligibles or team
            busy = await calendar.occupied(db, row.id, selected_day, [m.id for m in eligibles], services)
            if not any(s.id in mapping[m.id] and calendar.free_slots(listing, m, s, selected_day, busy)
                       for m in eligibles for s in suitable):
                continue
        if skipped < (page - 1) * 18:
            skipped += 1
            continue
        results.append(row)
        if len(results) >= 19:
            break
    await iter_rows.close()
    filters = {"city": city, "q": q, "max_price": max_price or "", "day": day, "sort": sort, "saved": "true" if saved else "false"}
    return shell("directory", results=results[:18], client=client, city=city, q=q, category=category, sort=sort, saved=saved,
                 favorites=favorites, categories=CATEGORIES, day=day, max_price=max_price, page=page, next_page=len(results) > 18,
                 search=urlencode({**filters, "category": category}), category_search=urlencode(filters),
                 filtered=bool(city or q or max_price or day or category or saved))


@router.post(PREFIX + "/zaklad/{business_id}/favorite")
async def change_favorite(business_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    await get_listing(db, business_id)
    form = await request.form()
    choice = form.get("favorite")
    if choice not in {"yes", "no"}:
        raise HTTPException(422)
    identifiers = (client.id, business_id)
    favorite = await db.get(MarketplaceFavorite, identifiers)
    if choice == "yes" and not favorite:
        db.add(MarketplaceFavorite(client_id=client.id, business_id=business_id))
    if choice == "no" and favorite:
        await db.delete(favorite)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    filters = {field: str(form.get(field, ""))[:100] for field in ("q", "city", "day", "max_price", "category", "sort", "saved", "page")}
    return redirect(PREFIX + "?" + urlencode({field: value for field, value in filters.items() if value}) + f"#shop-{business_id}")


async def shop_page(business_id, request, db, *, day="", service_id=0, master_id=0, visit_id=0, error="", status=200):
    business, listing = await get_listing(db, business_id)
    client = await current_client(request, db)
    services, team, mapping = await calendar.services_and_team(db, business_id)
    selected = next((item for item in services if item.id == service_id), None)
    specialist = next((m for m in team if m.id == master_id and selected and selected.id in mapping[m.id]), None)
    chosen_day = calendar.date_in_range(day) if day else calendar.now().date()
    slots = []
    if specialist and chosen_day:
        busy = await calendar.occupied(db, business_id, chosen_day, [specialist.id], services, exclude=visit_id or None)
        slots = calendar.free_slots(listing, specialist, selected, chosen_day, busy)
    reviews = (await db.execute(select(MarketplaceReview, MarketplaceClient.name, Master.name)
        .join(Appointment, Appointment.id == MarketplaceReview.appointment_id)
        .join(MarketplaceVisit, MarketplaceVisit.appointment_id == Appointment.id)
        .join(MarketplaceClient, MarketplaceClient.id == MarketplaceVisit.client_id)
        .outerjoin(Master, Master.id == Appointment.master_id)
        .where(Appointment.business_id == business.id, Appointment.status == "completed")
        .order_by(MarketplaceReview.created_at.desc()).limit(30))).all()
    photos = (await db.execute(select(MarketplacePhoto.id, MarketplacePhoto.caption)
                               .where(MarketplacePhoto.business_id == business_id).order_by(MarketplacePhoto.id))).all()
    return shell("shop", status=status, error=error, client=client, business=business, listing=listing,
                 services=services, team=[m for m in team if not selected or selected.id in mapping[m.id]],
                 reviews=reviews, photos=photos, day=str(chosen_day or ""), today=str(calendar.now().date()),
                 max_day=str(calendar.now().date()+timedelta(days=60)), service_id=service_id,
                 master_id=master_id, slots=[slot.strftime("%H:%M") for slot in slots], visit_id=visit_id,
                 back=request.url.path + "?" + urlencode({"day": day, "service_id": service_id, "master_id": master_id}))


@router.get(PREFIX + "/zaklad/{business_id}")
async def shop(business_id: int, request: Request, day: str = "", service_id: int = 0, master_id: int = 0,
               db: AsyncSession = Depends(get_db)):
    return await shop_page(business_id, request, db, day=day, service_id=service_id, master_id=master_id)


def local_next(value):
    if value.startswith(PREFIX + "/zaklad/") and re.fullmatch(r"/[a-z/0-9]+(?:\?[A-Za-z0-9_=%&+.-]*)?", value) and len(value) < 350:
        return value
    return PREFIX + "/account"


@router.get(PREFIX + "/login")
async def login(next: str = ""):
    return shell("client-auth", mode="login", next=local_next(next))


@router.post(PREFIX + "/login")
async def login_post(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    phone = calendar.normalize_phone(str(form.get("phone", ""))[:40])
    next_url = local_next(str(form.get("next", "")))
    password = str(form.get("password", ""))
    if not LOGIN_LIMIT.allow("ip:" + ip(request)) or not LOGIN_LIMIT.allow("phone:" + phone):
        return shell("client-auth", status=429, mode="login", next=next_url, error="Забагато спроб. Спробуйте пізніше.")
    client = await db.scalar(select(MarketplaceClient).where(MarketplaceClient.phone == phone))
    encoded = client.password if client else await run_in_threadpool(dummy_password_hash)
    valid = len(password) <= 1024 and await run_in_threadpool(verify_password, password, encoded)
    if not client or not valid:
        return shell("client-auth", status=401, mode="login", next=next_url, error="Телефон або пароль не збігаються.")
    identity = client.id
    await db.rollback()
    try:
        await phone_auth.issue(request, db, phone_auth.SIGNIN_CUSTOMER, phone, identity=identity, destination=next_url)
    except phone_auth.ChallengeError as error:
        return shell("client-auth", status=error.status, mode="login", next=next_url, error=str(error))
    request.session.pop(CLIENT, None)
    return redirect(PREFIX + "/login/verify")


@router.get(PREFIX + "/login/verify")
async def verify_login(request: Request):
    challenge = phone_auth.pending(request, phone_auth.SIGNIN_CUSTOMER)
    if not challenge:
        return redirect(PREFIX + "/login")
    return shell("client-auth", mode="login-verify", next=challenge["destination"])


@router.post(PREFIX + "/login/verify")
async def verify_login_post(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    try:
        challenge = await phone_auth.consume(request, db, phone_auth.SIGNIN_CUSTOMER, str(form.get("code", "")).strip())
    except phone_auth.ChallengeError as error:
        pending = phone_auth.pending(request, phone_auth.SIGNIN_CUSTOMER)
        return shell("client-auth", status=error.status, mode="login-verify",
                     next=pending["destination"] if pending else PREFIX + "/account", error=str(error))
    client = await db.get(MarketplaceClient, challenge["identity"])
    if not client or client.phone != challenge["phone"]:
        return redirect(PREFIX + "/login")
    request.session[CLIENT] = client.id
    return redirect(local_next(challenge["destination"]))


@router.get(PREFIX + "/register")
async def register(next: str = ""):
    return shell("client-auth", mode="register", next=local_next(next), sms=bool(phone_auth.provider().sms_token))


@router.post(PREFIX + "/register")
async def send_code(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    phone = str(form.get("phone", ""))[:40]
    next_url = local_next(str(form.get("next", "")))
    try:
        await phone_auth.issue(request, db, phone_auth.SIGNUP_CUSTOMER, phone, destination=next_url)
    except phone_auth.ChallengeError as error:
        return shell("client-auth", status=error.status, mode="register", next=next_url,
                     sms=bool(phone_auth.provider().sms_token), error=str(error))
    return redirect(PREFIX + "/verify")


@router.get(PREFIX + "/verify")
async def verify(request: Request):
    challenge = phone_auth.pending(request, phone_auth.SIGNUP_CUSTOMER)
    if not challenge:
        return redirect(PREFIX + "/register")
    return shell("client-auth", mode="verify", next=challenge["destination"])


@router.post(PREFIX + "/verify")
async def verify_post(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    challenge = phone_auth.pending(request, phone_auth.SIGNUP_CUSTOMER)
    if not challenge:
        return redirect(PREFIX + "/register")
    next_url = challenge["destination"]
    code, name, password = (str(form.get(field, "")).strip() if field != "password" else str(form.get(field, ""))
                            for field in ("code", "name", "password"))
    if not 1 <= len(name) <= 120 or not 8 <= len(password) <= 1024:
        return shell("client-auth", status=422, mode="verify", next=next_url, error="Перевірте ім’я та пароль.")
    try:
        await phone_auth.consume(request, db, phone_auth.SIGNUP_CUSTOMER, code)
    except phone_auth.ChallengeError as error:
        return shell("client-auth", status=error.status, mode="verify", next=next_url, error=str(error))
    phone = challenge["phone"]
    client = await db.scalar(select(MarketplaceClient).where(MarketplaceClient.phone == phone))
    if client:
        return shell("client-auth", mode="login", next=next_url, error="Цей номер уже має акаунт. Увійдіть із паролем.")
    hashed = await run_in_threadpool(hash_password, password)
    client = MarketplaceClient(phone=phone, name=name, password=hashed)
    db.add(client)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return shell("client-auth", mode="login", next=next_url, error="Цей номер уже має акаунт. Увійдіть із паролем.")
    request.session[CLIENT] = client.id
    return redirect(local_next(next_url))


@router.post(PREFIX + "/logout")
async def logout(request: Request):
    request.session.pop(CLIENT, None)
    phone_auth.clear(request, phone_auth.SIGNIN_CUSTOMER, phone_auth.SIGNUP_CUSTOMER)
    return redirect(PREFIX)


async def owned_visit(db, client, appointment_id):
    if not client:
        raise HTTPException(401, "Увійдіть до свого кабінету.")
    result = (await db.execute(select(Appointment, MarketplaceVisit).join(
        MarketplaceVisit, MarketplaceVisit.appointment_id == Appointment.id
    ).where(Appointment.id == appointment_id, MarketplaceVisit.client_id == client.id))).first()
    if not result:
        raise HTTPException(404)
    return result


@router.post(PREFIX + "/zaklad/{business_id}/book")
async def book(business_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    if not BOOK_LIMIT.allow(str(client.id)):
        raise HTTPException(429)
    form = await request.form()
    day, hour = str(form.get("day", "")), str(form.get("hour", ""))
    chosen_day = calendar.date_in_range(day)
    try:
        service_id, master_id, visit_id = (int(form.get(field, "0")) for field in ("service_id", "master_id", "visit_id"))
        start = datetime.combine(chosen_day, time.fromisoformat(hour)) if chosen_day else None
    except (TypeError, ValueError):
        raise HTTPException(422, "Перевірте дату, час, майстра й послугу.")
    await calendar.lock_calendar(db, business_id)
    business, listing = await get_listing(db, business_id)
    services, team, mapping = await calendar.services_and_team(db, business_id)
    service = next((s for s in services if s.id == service_id), None)
    master = next((m for m in team if m.id == master_id), None)
    if not service or not master or service.id not in mapping[master.id] or not start:
        raise HTTPException(422, "Ця комбінація послуги, часу й майстра недоступна.")
    appointment, visit = (await owned_visit(db, client, visit_id)) if visit_id else (None, None)
    if appointment and (appointment.business_id != business_id or appointment.status != "confirmed" or appointment.appointment_time <= calendar.now()):
        raise HTTPException(409, "Цей візит уже не можна перенести.")
    busy = await calendar.occupied(db, business_id, chosen_day, [master_id], services, exclude=visit_id or None)
    if start not in calendar.free_slots(listing, master, service, chosen_day, busy):
        return await shop_page(business_id, request, db, day=day, service_id=service_id, master_id=master_id, visit_id=visit_id,
                               error="Цей час уже зайнято. Оберіть інший слот.", status=409)
    phone_forms = {client.phone, client.phone[1:]}
    if client.phone.startswith("+380"):
        phone_forms.add(client.phone[3:])
    matches = (await db.scalars(select(Customer).where(Customer.business_id == business_id,
                  Customer.phone_number.in_(phone_forms)).order_by(Customer.id))).all()
    if any(c.is_blocked for c in matches):
        raise HTTPException(403, "Цей заклад не приймає запис із вашого акаунта.")
    customer = next(iter(matches), None)
    if not customer:
        customer = Customer(business_id=business_id, phone_number=client.phone, name=client.name)
        db.add(customer)
        await db.flush()
    if not appointment:
        appointment = Appointment(business_id=business_id, customer_id=customer.id, source="marketplace",
                                  master_id=master_id, appointment_time=start, service_type=service.name, cost=service.price)
        db.add(appointment)
        await db.flush()
        db.add(MarketplaceVisit(appointment_id=appointment.id, client_id=client.id, duration=service.duration))
    else:
        appointment.appointment_time, appointment.master_id = start, master_id
        appointment.service_type, appointment.cost, appointment.reminder_sent = service.name, service.price, False
        visit.duration = service.duration
    db.add(ActionLog(business_id=business_id, action="Перенесення візиту" if visit_id else "Онлайн-запис",
                     details=f"Каталог SafeOrbit · #{appointment.id}"))
    await db.commit()
    await send_new_appointment_notifications(business, appointment, db)
    return redirect(PREFIX + "/account?done=" + ("moved" if visit_id else "booked"))


@router.get(PREFIX + "/account")
async def account(request: Request, done: str = "", db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        return redirect(PREFIX + "/login")
    rows = (await db.execute(select(Appointment, Business.name, Master.name, MarketplaceReview)
        .join(MarketplaceVisit, MarketplaceVisit.appointment_id == Appointment.id)
        .join(Business, Business.id == Appointment.business_id).outerjoin(Master, Master.id == Appointment.master_id)
        .outerjoin(MarketplaceReview, MarketplaceReview.appointment_id == Appointment.id)
        .where(MarketplaceVisit.client_id == client.id).order_by(Appointment.appointment_time.desc()))).all()
    return shell("account", client=client, rows=rows, statuses=STATUSES, now=calendar.now(), done=done)


@router.post(PREFIX + "/account")
async def update_account(request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    if not client:
        raise HTTPException(401)
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not 1 <= len(name) <= 120:
        raise HTTPException(422, "Введіть ім’я.")
    client.name = name
    await db.commit()
    return redirect(PREFIX + "/account")


@router.get(PREFIX + "/visits/{appointment_id}/move")
async def move(appointment_id: int, request: Request, day: str = "", service_id: int = 0, master_id: int = 0,
               db: AsyncSession = Depends(get_db)):
    visit, _ = await owned_visit(db, await current_client(request, db), appointment_id)
    if visit.status != "confirmed" or visit.appointment_time <= calendar.now():
        raise HTTPException(409)
    return await shop_page(visit.business_id, request, db, day=day, service_id=service_id,
                           master_id=master_id, visit_id=visit.id)


@router.post(PREFIX + "/visits/{appointment_id}/cancel")
async def cancel(appointment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    client = await current_client(request, db)
    appointment, _ = await owned_visit(db, client, appointment_id)
    await calendar.lock_calendar(db, appointment.business_id)
    changed = await db.execute(update(Appointment).where(Appointment.id == appointment.id, Appointment.status == "confirmed",
                       Appointment.appointment_time > calendar.now()).values(status="cancelled"))
    if not changed.rowcount:
        raise HTTPException(409, "Цей візит уже не можна скасувати.")
    db.add(ActionLog(business_id=appointment.business_id, action="Скасування візиту", details=f"Каталог SafeOrbit · #{appointment.id}"))
    await db.commit()
    return redirect(PREFIX + "/account?done=cancelled")


@router.post(PREFIX + "/visits/{appointment_id}/review")
async def review(appointment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    appointment, _ = await owned_visit(db, await current_client(request, db), appointment_id)
    if appointment.status != "completed" or appointment.appointment_time > calendar.now():
        raise HTTPException(409, "Відгук доступний після візиту.")
    form = await request.form()
    rating, comment = str(form.get("rating", "")), str(form.get("comment", "")).strip()
    if rating not in {"1", "2", "3", "4", "5"} or len(comment) > 1200:
        raise HTTPException(422, "Перевірте оцінку та довжину відгуку.")
    db.add(MarketplaceReview(appointment_id=appointment.id, rating=int(rating), comment=comment))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Ви вже залишили відгук про цей візит.")
    return redirect(PREFIX + "/account?done=review")


@router.get("/workspace/listing")
async def listing_settings(user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    if "directory" not in allowed_modules(user.business):
        raise HTTPException(404)
    listing = await db.get(MarketplaceListing, user.business_id)
    services, team, _ = await calendar.services_and_team(db, user.business_id)
    photos = (await db.execute(select(MarketplacePhoto.id, MarketplacePhoto.caption)
                               .where(MarketplacePhoto.business_id == user.business_id).order_by(MarketplacePhoto.id))).all()
    categories = (await db.scalars(select(MarketplaceListingCategory.category).where(
        MarketplaceListingCategory.business_id == user.business_id))).all()
    return shell("listing", business=user.business, listing=listing, days=DAYS, services=services, team=team,
                 photos=photos, categories=CATEGORIES, chosen_categories=categories)


@router.post("/workspace/listing")
async def save_listing(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    if "directory" not in allowed_modules(user.business):
        raise HTTPException(404)
    form = await request.form()
    published = form.get("published") == "yes"
    city, address, description = (str(form.get(key, "")).strip() for key in ("city", "address", "description"))
    opens, closes = (str(form.get(key, "")) for key in ("opens", "closes"))
    days = sorted(set(form.getlist("days")))
    categories = set(form.getlist("category"))
    if len(categories) > 4 or not categories.issubset(CATEGORIES):
        raise HTTPException(422, "Можна вибрати до чотирьох категорій.")
    try:
        valid_hours = bool(re.fullmatch(r"\d{2}:\d{2}", opens) and re.fullmatch(r"\d{2}:\d{2}", closes)
                           and time.fromisoformat(opens) < time.fromisoformat(closes))
    except ValueError:
        valid_hours = False
    if not (1 <= len(city) <= 100 and 1 <= len(address) <= 220 and len(description) <= 1500 and days
            and all(day in set("0123456") for day in days) and valid_hours):
        raise HTTPException(422, "Перевірте адресу, дні та години прийому.")
    await calendar.lock_calendar(db, user.business_id)
    services, team, _ = await calendar.services_and_team(db, user.business_id)
    if published and (not services or not team):
        raise HTTPException(422, "Додайте майстра і послугу в налаштуваннях.")
    listing = await db.get(MarketplaceListing, user.business_id)
    if not listing:
        listing = MarketplaceListing(business_id=user.business_id)
        db.add(listing)
    listing.city, listing.address, listing.description = city, address, description
    listing.open_days, listing.opens, listing.closes = "".join(days), opens, closes
    listing.published = published
    await db.flush()
    current_categories = (await db.scalars(select(MarketplaceListingCategory).where(
        MarketplaceListingCategory.business_id == user.business_id))).all()
    for item in current_categories:
        if item.category not in categories:
            await db.delete(item)
    db.add_all(MarketplaceListingCategory(business_id=user.business_id, category=key)
               for key in categories - {item.category for item in current_categories})
    await db.commit()
    return redirect("/workspace/listing")


def clean_photo(raw):
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(raw)) as photo:
            if photo.width * photo.height > 20000000:
                raise ValueError("Image too large")
            image = ImageOps.exif_transpose(photo).convert("RGB")
            image.thumbnail((1200, 900))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=86, optimize=True)
            return out.getvalue()
    except Image.DecompressionBombError as exc:
        raise ValueError("Image too large") from exc


@router.post("/workspace/listing/photos")
async def add_photo(request: Request, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    if "directory" not in allowed_modules(user.business):
        raise HTTPException(404)
    form = await request.form()
    caption = str(form.get("caption", "")).strip()
    if len(caption) > 120:
        raise HTTPException(422, "Підпис має бути коротшим за 120 символів.")
    try:
        _, _, raw = await uploaded(form, kinds={"jpg", "png"})
        content = await run_in_threadpool(clean_photo, raw)
    except (ToolError, ValueError, OSError):
        raise HTTPException(422, "Додайте придатне до перегляду фото JPG або PNG до 4 МБ.")
    await calendar.lock_calendar(db, user.business_id)
    if not await db.get(MarketplaceListing, user.business_id):
        raise HTTPException(409, "Спочатку збережіть профіль.")
    count = await db.scalar(select(func.count(MarketplacePhoto.id)).where(MarketplacePhoto.business_id == user.business_id))
    if count >= 6:
        raise HTTPException(422, "Можна додати до 6 фотографій.")
    db.add(MarketplacePhoto(business_id=user.business_id, caption=caption, content=content))
    await db.commit()
    return redirect("/workspace/listing#photos")


@router.get(PREFIX + "/photo/{photo_id}")
async def gallery_photo(photo_id: int, db: AsyncSession = Depends(get_db)):
    data = await db.scalar(select(MarketplacePhoto.content).join(Business, Business.id == MarketplacePhoto.business_id)
        .join(MarketplaceListing, MarketplaceListing.business_id == Business.id)
        .where(MarketplacePhoto.id == photo_id, Business.is_active.is_(True), MarketplaceListing.published.is_(True)))
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/jpeg")


@router.post("/workspace/listing/photos/{photo_id}/delete")
async def remove_photo(photo_id: int, user=Depends(workspace_user), db: AsyncSession = Depends(get_db)):
    if "directory" not in allowed_modules(user.business):
        raise HTTPException(404)
    await db.execute(delete(MarketplacePhoto).where(MarketplacePhoto.id == photo_id, MarketplacePhoto.business_id == user.business_id))
    await db.commit()
    return redirect("/workspace/listing#photos")
