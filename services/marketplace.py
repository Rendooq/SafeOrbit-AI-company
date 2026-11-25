"""Appointment availability against the existing team calendar."""
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import select, update

from config import UA_TZ
from models import Appointment, Business, Master, MasterService, Service
from models_platform import MarketplaceListing, MarketplaceVisit


def now():
    return datetime.now(UA_TZ).replace(tzinfo=None)


def local_time(value):
    return value.astimezone(UA_TZ).replace(tzinfo=None) if value.tzinfo else value


def normalize_phone(value):
    clean = re.sub(r"[\s.()-]", "", value)
    if re.fullmatch(r"0[0-9]{9}", clean):
        clean = "+38" + clean
    if re.fullmatch(r"380[0-9]{9}", clean):
        clean = "+" + clean
    return clean if re.fullmatch(r"\+[1-9][0-9]{7,14}", clean) else ""


def date_in_range(day):
    try:
        selected = date.fromisoformat(day)
        today = now().date()
        return selected if today <= selected <= today + timedelta(days=60) else None
    except (TypeError, ValueError):
        return None


async def lock_calendar(db, business_id):
    # PostgreSQL locks the tenant row. SQLite takes a write lock for this transaction.
    await db.execute(update(Business).where(Business.id == business_id).values(id=Business.id)
                     .execution_options(synchronize_session=False))


async def services_and_team(db, business_id):
    services = (await db.scalars(select(Service).where(Service.business_id == business_id, Service.duration > 0,
        Service.duration <= 720, Service.price >= 0).order_by(Service.name, Service.id))).all()
    team = (await db.scalars(select(Master).where(Master.business_id == business_id, Master.is_active.is_(True))
                            .order_by(Master.name, Master.id))).all()
    mapping = set((await db.execute(select(MasterService.master_id, MasterService.service_id)
                  .where(MasterService.master_id.in_([person.id for person in team])))).all())
    assigned = {mid for mid, _ in mapping}
    return services, team, {person.id: {service.id for service in services
                                       if person.id not in assigned or (person.id, service.id) in mapping} for person in team}


def working_period(listing, master, day):
    if str(day.weekday()) not in listing.open_days:
        return None
    start, end = time.fromisoformat(listing.opens), time.fromisoformat(listing.closes)
    if master.working_hours:
        match = re.fullmatch(r"(?:(Пн|Вт|Ср|Чт|Пт|Сб|Нд)(?:\s*[-–]\s*(Пн|Вт|Ср|Чт|Пт|Сб|Нд))?\s*:\s*)?(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})",
                             master.working_hours.strip(), re.IGNORECASE)
        if not match:
            return None
        days = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"]
        if match[1]:
            first = days.index(match[1].casefold())
            last = days.index((match[2] or match[1]).casefold())
            if (day.weekday() - first) % 7 > (last - first) % 7:
                return None
        try:
            start = max(start, time.fromisoformat(match[3]))
            end = min(end, time.fromisoformat(match[4]))
        except ValueError:
            return None
    return datetime.combine(day, start), datetime.combine(day, end)


async def occupied(db, business_id, day, master_ids, services, exclude=None):
    midnight = datetime.combine(day, time.min)
    query = select(Appointment, MarketplaceVisit.duration).outerjoin(
        MarketplaceVisit, MarketplaceVisit.appointment_id == Appointment.id
    ).where(
        Appointment.business_id == business_id, Appointment.status.not_in(("cancelled", "no_show")),
        Appointment.appointment_time >= midnight - timedelta(hours=12),
        Appointment.appointment_time < midnight + timedelta(days=1),
    )
    if master_ids is not None:
        query = query.where(Appointment.master_id.in_(master_ids) | Appointment.master_id.is_(None))
    if exclude is not None:
        query = query.where(Appointment.id != exclude)
    estimated = {service.name: service.duration for service in services}
    return [(appt.master_id, appt.appointment_time,
             appt.appointment_time + timedelta(minutes=duration or estimated.get(appt.service_type, 90)))
            for appt, duration in (await db.execute(query)).all()]


async def conflicts(db, business_id, start, master_id, service_name, *, exclude=None, duration=None, published_only=False):
    if published_only and not await db.scalar(select(MarketplaceListing.published).where(MarketplaceListing.business_id == business_id)):
        return False
    await lock_calendar(db, business_id)
    start = local_time(start)
    services = (await db.scalars(select(Service).where(Service.business_id == business_id))).all()
    if duration is None:
        duration = next((s.duration for s in services if s.name == service_name), 90)
    end = start + timedelta(minutes=max(1, min(duration or 90, 720)))
    scope = None if master_id is None else [master_id]
    pending = await occupied(db, business_id, start.date(), scope, services, exclude)
    if end.date() != start.date():
        pending.extend(await occupied(db, business_id, end.date(), scope, services, exclude))
    return any(start < occupied_end and end > occupied_start for _, occupied_start, occupied_end in pending)


def free_slots(listing, master, service, day, busy):
    period = working_period(listing, master, day)
    if not period:
        return []
    start, last = period
    interval, duration = timedelta(minutes=15), timedelta(minutes=service.duration)
    available = []
    current = now()
    while start + duration <= last:
        if start > current and not any(mid in {None, master.id} and start < end and start + duration > begin
                                      for mid, begin, end in busy):
            available.append(start)
        start += interval
    return available
