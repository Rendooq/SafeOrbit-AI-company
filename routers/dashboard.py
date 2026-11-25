import csv
import io
import json
import html
import math
from datetime import date, datetime, time, timedelta
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, desc, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import LABELS, UA_TZ
from database import get_db
from dependencies import get_current_user
from models import User, Appointment, Master, Service, Customer, Business, ActionLog, ChatLog, Product
from ui import get_layout
from utils.templates import render_template
from utils.schedule import personal_schedule
from services.marketplace import conflicts
from utils.logger import log_action
from sqlalchemy import case
from services.ai_service import process_ai_request
from services.sms import send_sms
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin Panel"])

def editor_args(appointment):
    return [appointment.id, appointment.appointment_time.strftime("%Y-%m-%d"),
            appointment.appointment_time.strftime("%H:%M"), appointment.status, appointment.cost,
            str(appointment.master_id or ""), appointment.delivery_address or "",
            appointment.ttn or "", appointment.delivery_status or "pending"]


def overview_amount(value):
    return f"{value or 0:,.2f}".removesuffix(".00").replace(",", " ")


def saved_agenda(message, appointment, period, specialist):
    location = f"/admin?msg={message}"
    if period in {7, 30}:
        master = (appointment.master_id or 0) if specialist else 0
        location += f"&day={appointment.appointment_time.date().isoformat()}&specialist={master}&period={period}#day-agenda"
    return RedirectResponse(location, status_code=303)


async def day_overview(db, business_id, filters, day, period):
    day_start = datetime.combine(day, time.min)
    end = day_start + timedelta(days=1)
    visits = (await db.scalars(select(Appointment).options(
        joinedload(Appointment.customer.and_(Customer.business_id == business_id)),
        joinedload(Appointment.master.and_(Master.business_id == business_id)),
    ).where(*filters, Appointment.appointment_time >= day_start, Appointment.appointment_time < end)
      .order_by(Appointment.appointment_time, Appointment.id))).all()
    lanes = {}
    slots = {}
    clients = {}
    active_count = completed_count = 0
    earned = 0.0
    for visit in visits:
        staff_id = visit.master.id if visit.master else 0
        lanes[staff_id] = visit.master.name if visit.master else "Без спеціаліста"
        clock = visit.appointment_time.strftime("%H:%M")
        slot = slots.setdefault(clock, {})
        name = visit.customer.name if visit.customer and visit.customer.name else "Гість"
        slot.setdefault(staff_id, []).append(dict(
            name=name, service=visit.service_type, status=visit.status,
            status_label=REPORT_STATUS.get(visit.status, "Інше"), args=editor_args(visit),
        ))
        if visit.status != "cancelled":
            active_count += 1
            if visit.customer and visit.customer_id not in clients:
                clients[visit.customer_id] = dict(name=name, time=clock, phone=visit.customer.phone_number)
        if visit.status == "completed":
            completed_count += 1
            earned += visit.cost or 0
    days = [day - timedelta(days=offset) for offset in reversed(range(period))]
    totals = dict.fromkeys(days, 0.0)
    bucket = func.date(Appointment.appointment_time)
    amounts = await db.execute(select(bucket, func.sum(Appointment.cost)).where(
        *filters, Appointment.status == "completed",
        Appointment.appointment_time >= datetime.combine(days[0], time.min),
        Appointment.appointment_time < end,
    ).group_by(bucket))
    for key, amount in amounts:
        totals[date.fromisoformat(key) if isinstance(key, str) else key] = amount or 0
    ordered_lanes = sorted(lanes.items(), key=lambda item: (item[0] == 0, item[1].casefold(), item[0]))
    return dict(
        lanes=ordered_lanes, columns={staff_id: index + 2 for index, (staff_id, _) in enumerate(ordered_lanes)},
        lane_names=lanes, slots=slots, clients=clients.values(), active_count=active_count,
        customer_count=len(clients), daily_revenue=overview_amount(earned),
        completed_percent=round(100 * completed_count / active_count) if active_count else 0,
        period_start=days[0], period_revenue=overview_amount(sum(totals.values())),
        chart_json=json.dumps({"labels": [d.strftime("%d.%m") for d in days], "values": [totals[d] for d in days]}),
    )


async def can_manage_appointment(user, appointment, db):
    if not user or appointment.business_id != user.business_id:
        return False
    if user.role == "master":
        return not await personal_schedule(user, db) or appointment.master_id == user.master_id
    return user.role in {"owner", "admin", "manager"}


async def valid_assignment(user, master_id, db):
    restricted = await personal_schedule(user, db)
    if master_id is None:
        return not restricted
    master = await db.get(Master, master_id)
    return bool(master and master.business_id == user.business_id and master.is_active
                and (not restricted or master_id == user.master_id))


@router.get("/admin", response_class=HTMLResponse)
async def owner_dash(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
                     day: Optional[date] = None, specialist: int = 0, period: int = 7):
    if not user or user.role not in ["owner", "admin", "manager", "master"]: return RedirectResponse("/", status_code=303)
    
    is_demo = getattr(user, "is_demo_workspace", False)
    external_action_class = "d-none" if is_demo else ""
    is_limited_master = await personal_schedule(user, db)

    now = datetime.now(UA_TZ)
    today_start = now.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    filters = [Appointment.business_id == user.business_id]
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    agg_stmt = select(
        func.sum(case((and_(Appointment.status != 'cancelled', Appointment.appointment_time >= today_start, Appointment.appointment_time < today_start + timedelta(days=1)), 1), else_=0)),
        func.sum(case((and_(Appointment.status != 'cancelled', Appointment.appointment_time >= month_start, Appointment.appointment_time < next_month), 1), else_=0)),
        func.sum(case((and_(Appointment.status == 'completed', Appointment.appointment_time >= month_start, Appointment.appointment_time < next_month), Appointment.cost), else_=0)),
        func.sum(case((Appointment.status == 'completed', Appointment.cost), else_=0))
    ).where(and_(*filters))
    agg_res = await db.execute(agg_stmt)
    agg_row = agg_res.first()
    c_day = int(agg_row[0] or 0) if agg_row else 0
    c_month = int(agg_row[1] or 0) if agg_row else 0
    rev_month = agg_row[2] or 0 if agg_row else 0
    rev_total = agg_row[3] or 0 if agg_row else 0

    biz_type = user.business.type if user.business else "barbershop"
    l = LABELS.get(biz_type, LABELS["generic"])

    stmt_status = select(Appointment.status, func.count(Appointment.id)).where(and_(
        *filters, Appointment.appointment_time >= month_start, Appointment.appointment_time < next_month
    )).group_by(Appointment.status)
    res_status = await db.execute(stmt_status)
    s_map = dict(res_status.all())
    
    masters = (await db.execute(select(Master).where(and_(Master.business_id == user.business_id, Master.is_active == True)))).scalars().all()
    if is_limited_master:
        masters = [master for master in masters if master.id == user.master_id]
    services = (await db.execute(select(Service).where(Service.business_id == user.business_id))).scalars().all()
    services_json = json.dumps({s.id: {'price': s.price, 'name': s.name} for s in services}).replace("<", "\\u003c")

    stmt = select(Appointment).options(joinedload(Appointment.customer.and_(Customer.business_id == user.business_id)),
        joinedload(Appointment.master.and_(Master.business_id == user.business_id))).where(and_(*filters)).order_by(desc(Appointment.appointment_time)).limit(10)
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    status_badges = {
        "confirmed": "<span class='badge bg-primary bg-opacity-10 text-primary'>Очікується</span>",
        "completed": "<span class='badge bg-success bg-opacity-10 text-success'>Виконано</span>",
        "cancelled": "<span class='badge bg-danger bg-opacity-10 text-danger'>Скасовано</span>"
    }

    master_options = "".join([f'<option value="{m.id}">{html.escape(m.name)}</option>' for m in masters])
    service_options = "".join([f'<option value="{html.escape(s.name, quote=True)}" data-id="{s.id}">{html.escape(s.name)} ({s.price} грн)</option>' for s in services])

    src_stmt = select(
        func.sum(case((Appointment.source == 'ai', 1), else_=0)),
        func.sum(case((Appointment.source == 'manual', 1), else_=0))
    ).where(and_(*filters))
    src_row = (await db.execute(src_stmt)).first()
    ai_count = int(src_row[0] or 0) if src_row else 0
    manual_count = int(src_row[1] or 0) if src_row else 0
    
    top_services = (await db.execute(select(Appointment.service_type, func.count(Appointment.id)).where(and_(*filters)).group_by(Appointment.service_type).order_by(desc(func.count(Appointment.id))).limit(5))).all()
    
    top_clients = (await db.execute(
        select(Customer.name, Customer.phone_number, func.count(Appointment.id).label('appts_count'), func.sum(Appointment.cost).label('total_spent'))
        .join(Appointment)
        .where(*filters, Customer.business_id == user.business_id, Appointment.status == 'completed')
        .group_by(Customer.id)
        .order_by(desc(func.count(Appointment.id)))
        .limit(5)
    )).all()

    # Form Top Clients list HTML
    top_clients_html = ""
    for name, phone, count, spent in top_clients:
        initials = "".join([n[0] for n in name.split()[:2]]).upper() if name else "??"
        is_vip = count >= 10
        badge_class = "vip" if is_vip else ("new" if count <= 2 else "regular")
        badge_text = "VIP" if is_vip else ("НОВИЙ" if count <= 2 else "ПОСТІЙНИЙ")
        
        top_clients_html += f"""
        <div class="client-item d-flex align-items-center mb-3 p-3 glass-card max-w-full overflow-hidden" style="border-radius: 18px;">
            <div class="client-avatar d-flex align-items-center justify-content-center fw-bold me-3 flex-shrink-0" style="width: 48px; height: 48px; border-radius: 14px; background: rgba(255,255,255,0.05); color: #fff;">{html.escape(initials)}</div>
            <div class="client-info flex-grow-1 min-w-0">
                <div class="client-name fw-800 text-white break-words overflow-hidden min-w-0" style="font-size: 14px;">{html.escape(name or 'Гість')}</div>
                <div class="client-meta opacity-50 break-words overflow-hidden min-w-0" style="font-size: 11px;">{html.escape(phone or "")} • {count} візитів</div>
            </div>
            <div class="text-end flex-shrink-0 ms-2">
                <div class="fw-800 text-primary-glow mb-1" style="font-size: 13px;">{int(spent or 0)} ₴</div>
                <span class="badge {badge_class}" style="font-size: 9px; padding: 4px 8px; border-radius: 8px; background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.5); border: 0.5px solid rgba(255,255,255,0.1);">{badge_text}</span>
            </div>
        </div>
        """

    if is_limited_master:
        master_input = f'<input type="hidden" name="master_id" value="{user.master_id}">'
    else:
        master_input = f'<div class="col-md-12 min-w-0"><label class="form-label break-words">{l["master_single"]}</label><select name="master_id" class="form-select min-w-0"><option value="">-- Будь-який --</option>{master_options}</select></div>'

    delivery_input = f'<div class="col-md-12 min-w-0"><label class="form-label break-words">Адреса доставки (відділення пошти, місто)</label><input name="delivery_address" class="glass-input break-words overflow-hidden min-w-0" placeholder="Введіть адресу доставки..."></div>' if biz_type == 'retail' else ''

    delivery_display = 'block' if biz_type == 'retail' else 'none'
    rows = ""
    for a in appts:
        if not a.customer: continue
        d_str = a.appointment_time.strftime('%Y-%m-%d')
        t_str = a.appointment_time.strftime('%H:%M')
        badge = status_badges.get(a.status, "<span class='badge bg-secondary'>Інше</span>")
        master_name = f"<br><small class='text-muted'><i class='fas fa-user-tie me-1'></i>{html.escape(a.master.name)}</small>" if a.master else ""
        del_str = f"<br><small class='text-primary fw-bold'><i class='fas fa-truck me-1'></i>{html.escape(a.delivery_address)}</small>" if a.delivery_address else ""
        
        rows += f"""
        <tr>
            <td class="min-w-0 max-w-full">
                <div class="fw-bold text-truncate break-words overflow-hidden min-w-0" style="max-width: 200px;">{html.escape(a.customer.name or 'Гість')}</div>
                <div class="small text-muted text-truncate break-words overflow-hidden min-w-0" style="max-width: 200px;">{html.escape(a.customer.phone_number)}</div>
                {master_name}
                {del_str}
            </td>
            <td>
                <div class="fw-bold">{d_str}</div>
                <div class="small text-muted">{t_str}</div>
            </td>
            <td class="break-words overflow-hidden min-w-0">{html.escape(a.service_type)}</td>
            <td class="fw-bold">{a.cost} грн</td>
            <td>{badge}</td>
            <td class="text-end">
                <button class="btn-glass icon-btn me-1" data-legacy-edit="{a.id}" data-edit-args="{html.escape(json.dumps(editor_args(a)), quote=True)}"><i class="fas fa-edit"></i></button>
                <button class="btn-glass icon-btn me-1 {external_action_class}" onclick="openNotify({html.escape(json.dumps(a.customer.phone_number), quote=True)}, '{d_str}', '{t_str}')"><i class="fas fa-bell"></i></button>
                <a href="/admin/receipt/{a.id}" target="_blank" class="btn-glass icon-btn"><i class="fas fa-print"></i></a>
            </td>
        </tr>
        """

    stmt_broadcast = select(ActionLog).where(ActionLog.action == 'Розсилка', ActionLog.business_id.is_(None)).order_by(desc(ActionLog.created_at)).limit(1)
    latest_broadcast = (await db.execute(stmt_broadcast)).scalar_one_or_none()
    
    broadcast_html = ""
    if latest_broadcast and (datetime.now(UA_TZ).replace(tzinfo=None) - latest_broadcast.created_at).days <= 7:
        broadcast_html = f"""
        <div class="alert alert-info alert-dismissible fade show mb-4 d-flex align-items-center" role="alert" style="background: rgba(96, 165, 250, 0.1); border: 1px solid rgba(96, 165, 250, 0.2); color: #60a5fa; border-radius: 16px;">
            <i class="fas fa-bullhorn fa-2x me-3"></i>
            <div>
                <strong class="text-white">Нове оголошення від адміністрації:</strong><br>
                <span style="color: #cbd5e1;">{html.escape(latest_broadcast.details)}</span>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close" style="filter: invert(1) brightness(200%);"></button>
        </div>
        """

    content = f"""
    {broadcast_html}
    <div class="dashboard-stats mb-4">
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(175, 133, 255, 0.1); color: var(--accent-primary);"><i class="fas fa-calendar-day"></i></div>
            <div class="stat-info">
                <p class="stat-label">ВІЗИТІВ СЬОГОДНІ</p>
                <h3 class="stat-value">{c_day}</h3>
                <div class="stat-change"><i class="fas fa-clock me-1"></i>Сьогодні</div>
            </div>
        </div>
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(96, 165, 250, 0.1); color: var(--info);"><i class="fas fa-calendar-days"></i></div>
            <div class="stat-info">
                <p class="stat-label">ВІЗИТІВ МІСЯЦЬ</p>
                <h3 class="stat-value">{c_month}</h3>
                <div class="stat-change"><i class="fas fa-calendar-days me-1"></i>Поточний місяць</div>
            </div>
        </div>
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(52, 211, 153, 0.1); color: var(--success);"><i class="fas fa-wallet"></i></div>
            <div class="stat-info">
                <p class="stat-label">ДОХІД МІСЯЦЬ</p>
                <h3 class="stat-value">{int(rev_month)} ₴</h3>
                <div class="stat-change"><i class="fas fa-chart-bar me-1"></i>Обіг</div>
            </div>
        </div>
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(244, 114, 182, 0.1); color: var(--accent-pink);"><i class="fas fa-chart-line"></i></div>
            <div class="stat-info">
                <p class="stat-label">ДОХІД ВСЬОГО</p>
                <h3 class="stat-value">{int(rev_total)} ₴</h3>
                <div class="stat-change"><i class="fas fa-history me-1"></i>За весь період</div>
            </div>
        </div>
    </div>
    
    <div class="glass-card mb-4 p-2 dash-tabs-bar">
        <ul class="nav nav-pills" id="dashTabs" role="tablist" style="gap: 8px;">
            <li class="nav-item"><button class="nav-link active rounded-pill px-4 fw-600" data-bs-toggle="tab" data-bs-target="#tab-list"><i class="fas fa-list me-2"></i>Список</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="tab" data-bs-target="#tab-calendar"><i class="fas fa-calendar-days me-2"></i>Календар</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="tab" data-bs-target="#tab-analytics"><i class="fas fa-chart-pie me-2"></i>Аналітика</button></li>
        </ul>
    </div>

    <div class="tab-content">
        <div class="tab-pane fade show active" id="tab-list">
            <div class="row g-4 mb-4">
                <div class="col-lg-8 col-md-12">
                    <div class="glass-card">
                        <div class="d-flex justify-content-between align-items-center mb-4">
                            <h5 class="fw-800 text-white m-0">{l['new_appt']}</h5>
                            <div class="d-flex gap-2 {external_action_class}">
                                <button type="button" class="btn-glass py-2" style="font-size: 12px; background: rgba(175, 133, 255, 0.1); color: var(--accent-primary) !important; border-color: rgba(175, 133, 255, 0.3);" onclick="bootstrap.Modal.getOrCreateInstance(document.getElementById('aiModal')).show()">
                                    <i class="fas fa-robot me-1"></i> ШІ
                                </button>
                                <a href="/widget/{user.business_id}" target="_blank" class="btn-glass py-2" style="font-size: 12px;"><i class="fas fa-external-link-alt me-1"></i>Віджет</a>
                            </div>
                        </div>
                        <form action="/admin/add-appointment" method="post" class="row g-4 max-w-full">
                            <input type="hidden" name="overview_period" value="{period}"><input type="hidden" name="overview_specialist" value="{specialist}">
                            <div class="col-lg-6 col-md-12 min-w-0"><label class="form-label text-white-50 small fw-bold mb-2 break-words">КОНТАКТНИЙ НОМЕР</label><input name="phone" class="glass-input break-words overflow-hidden min-w-0" required placeholder="+380..."></div>
                            <div class="col-lg-6 col-md-12 min-w-0"><label class="form-label text-white-50 small fw-bold mb-2 break-words">ПРОФІЛЬ ГОСТЯ</label><input name="name" class="glass-input break-words overflow-hidden min-w-0" placeholder="Введіть ім'я"></div>
                            
                            <div class="col-lg-6 col-md-12 min-w-0"><label class="form-label text-white-50 small fw-bold mb-2 break-words">ОБРАНИЙ СЕРВІС</label>
                                <select name="service" id="serviceSelect" class="form-select min-w-0" onchange="updatePrice()">
                                    <option value="">-- Оберіть сервіс --</option>
                                    {service_options}
                                    <option value="custom">Індивідуальний запит</option>
                                </select>
                                <input name="custom_service" id="customServiceInput" class="glass-input mt-2 d-none break-words overflow-hidden min-w-0" placeholder="Назва сервісу">
                            </div>
                            <div class="col-lg-6 col-md-12 min-w-0"><label class="form-label text-white-50 small fw-bold mb-2 break-words">СУМА ДО СПЛАТИ</label><input name="cost" id="costInput" type="number" step="0.01" class="glass-input break-words overflow-hidden min-w-0" placeholder="0.00"></div>
                            
                            {master_input}
                            {delivery_input}
                            
                            <div class="col-lg-4 col-md-6 min-w-0"><label class="form-label text-white-50 small fw-bold mb-2 break-words">ДАТА</label><input name="date" type="date" class="glass-input break-words overflow-hidden min-w-0" required></div>
                            <div class="col-lg-4 col-md-6 min-w-0"><label class="form-label text-white-50 small fw-bold mb-2 break-words">ЧАС</label><input name="time" type="time" class="glass-input break-words overflow-hidden min-w-0" required></div>
                            <div class="col-lg-4 col-md-12 d-flex align-items-end min-w-0"><button class="btn-primary-glow w-100 py-3 break-words overflow-hidden min-w-0"><i class="fas fa-check me-2"></i>Підтвердити запис</button></div>
                        </form>
                    </div>
                </div>
                <div class="col-lg-4 col-md-12">
                    <div class="glass-card p-4">
                        <h5 class="fw-800 text-white mb-4">Статистика</h5>
                        <div class="d-flex flex-column gap-2">
                            <div class="d-flex justify-content-between align-items-center p-2 px-3 rounded-4" style="background: rgba(96, 165, 250, 0.05); border: 0.5px solid rgba(96, 165, 250, 0.15);">
                                <span class="text-nowrap small fw-bold" style="color: #60a5fa;"><i class="fas fa-clock me-2"></i>Очікується</span>
                                <span class="badge bg-primary bg-opacity-20 text-primary" style="font-size: 12px !important;">{s_map.get('confirmed', 0)}</span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center p-2 px-3 rounded-4" style="background: rgba(52, 211, 153, 0.05); border: 0.5px solid rgba(52, 211, 153, 0.15);">
                                <span class="text-nowrap small fw-bold" style="color: #34d399;"><i class="fas fa-check me-2"></i>Виконано</span>
                                <span class="badge bg-success bg-opacity-20 text-success" style="font-size: 12px !important;">{s_map.get('completed', 0)}</span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center p-2 px-3 rounded-4" style="background: rgba(248, 113, 113, 0.05); border: 0.5px solid rgba(248, 113, 113, 0.15);">
                                <span class="text-nowrap small fw-bold" style="color: #f87171;"><i class="fas fa-times me-2"></i>Скасовано</span>
                                <span class="badge bg-danger bg-opacity-20 text-danger" style="font-size: 12px !important;">{s_map.get('cancelled', 0)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="glass-card">
                <h5 class="fw-800 text-white mb-4">{l['appts']}</h5>
                <div class="table-responsive w-full overflow-x-auto whitespace-nowrap block">
                    <table class="glass-table">
                        <thead><tr><th>Профіль гостя</th><th>Час</th><th>{l['service_single']}</th><th>Сума до сплати</th><th>Статус</th><th class="text-end">Дії</th></tr></thead>
                        <tbody>{rows if rows else '<tr><td colspan=6 class="text-center py-5 text-muted">Записів ще немає</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="tab-pane fade" id="tab-calendar">
            <div class="row g-4">
                <div class="col-lg-8 col-md-12">
                    <div class="custom-calendar">
                        <div class="calendar-month-year">
                            <h4 id="calendarMonthYear" class="fw-800 text-white m-0">Березень 2026</h4>
                            <div class="calendar-nav">
                                <button onclick="changeMonth(-1)"><i class="fas fa-chevron-left"></i></button>
                                <button onclick="changeMonth(1)"><i class="fas fa-chevron-right"></i></button>
                            </div>
                        </div>
                        <div class="weekdays">
                            <div class="weekday">Пн</div><div class="weekday">Вт</div><div class="weekday">Ср</div><div class="weekday">Чт</div><div class="weekday">Пт</div><div class="weekday">Сб</div><div class="weekday">Нд</div>
                        </div>
                        <div id="calendarDays" class="days-grid"></div>
                    </div>
                </div>
                <div class="col-lg-4 col-md-12">
                    <div class="glass-card h-100 p-4">
                        <h5 class="fw-800 text-white mb-4"><i class="fas fa-crown text-warning me-2"></i>{l.get('analytics_clients', 'Топ Гостей')}</h5>
                        <div class="client-list d-flex flex-column gap-3">
                            {top_clients_html if top_clients_html else '<div class="text-center p-5 text-muted small border-dashed rounded-4" style="border: 1px dashed rgba(255,255,255,0.1);">Поки немає завершених записів.</div>'}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="tab-pane fade" id="tab-analytics">
            <div class="row g-4">
                <div class="col-lg-4 col-md-12"><div class="glass-card p-4"><h6 class="fw-800 text-white text-center mb-4">Джерела записів</h6><div style="height: 300px;"><canvas id="chartSource"></canvas></div></div></div>
                <div class="col-lg-4 col-md-12"><div class="glass-card p-4"><h6 class="fw-800 text-white text-center mb-4">Популярні послуги</h6><div style="height: 300px;"><canvas id="chartServices"></canvas></div></div></div>
                <div class="col-lg-4 col-md-12"><div class="glass-card p-4"><h6 class="fw-800 text-white text-center mb-4">Цінність клієнтів</h6><div style="height: 300px;"><canvas id="chartLTV"></canvas></div></div></div>
            </div>
        </div>
    </div>
    
    <div class="modal fade" id="aiModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">AI Асистент</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <div class="modal-body overflow-y-auto">
            <div id="aiResponse" class="mb-4 p-4 rounded-4" style="background: rgba(255,255,255,0.02); min-height: 100px; color: rgba(255,255,255,0.8); font-size: 14px; border: 0.5px solid var(--glass-border); line-height: 1.6;">Запитайте щось про ваші записи...</div>
            <div class="input-group gap-2">
                <input id="aiQuestion" class="glass-input break-words overflow-hidden min-w-0" placeholder="Хто записаний на завтра?">
                <button class="btn-glass px-3" onclick="startDictation()"><i class="fas fa-microphone"></i></button>
                <button class="btn-primary-glow px-4" onclick="askAI()"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>
    </div></div></div>

    <div class="modal fade" id="notifyModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Надіслати нагадування</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <div class="modal-body overflow-y-auto">
            <input type="hidden" id="notifyPhone">
            <label class="form-label">Текст повідомлення</label>
            <textarea id="notifyMsg" class="glass-input mb-4" rows="3"></textarea>
            <div class="row g-3">
                <div class="col-6"><button id="btnSms" type="button" class="btn-glass w-100 py-3" onclick="sendSMS()"><i class="fas fa-comment-sms me-2 text-info"></i>SMS</button></div>
                <div class="col-6"><a id="btnWa" href="#" target="_blank" class="btn-glass w-100 py-3"><i class="fab fa-whatsapp me-2 text-success"></i>WhatsApp</a></div>
                <div class="col-6"><a id="btnViber" href="#" class="btn-glass w-100 py-3"><i class="fab fa-viber me-2" style="color: #7360f2;"></i>Viber</a></div>
                <div class="col-6"><a id="btnTg" href="#" target="_blank" class="btn-glass w-100 py-3"><i class="fab fa-telegram me-2 text-primary"></i>Telegram</a></div>
            </div>
        </div>
    </div></div></div>

    <div class="modal fade" id="editModal" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Редагування Запису</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/admin/update-appointment" method="post" class="d-flex flex-column h-100"><div class="modal-body overflow-y-auto">
            <input type="hidden" name="overview_period" value="{period}"><input type="hidden" name="overview_specialist" value="{specialist}">
            <input type="hidden" name="id" id="editId">
            <div class="row g-3">
                <div class="col-12 col-md-6"><label class="form-label">Дата</label><input name="date" type="date" id="editDate" class="glass-input" required></div>
                <div class="col-12 col-md-6"><label class="form-label">Час</label><input name="time" type="time" id="editTime" class="glass-input" required></div>
                <div class="col-md-12"><label class="form-label">Сума (грн)</label><input name="cost" type="number" step="0.01" id="editCost" class="glass-input"></div>
                <div class="col-md-12"><label class="form-label">{l['master_single']}</label><select name="master_id" id="editMaster" class="form-select"><option value="">Без спеціаліста</option>{master_options}</select></div>
                
                <div class="col-12 delivery-fields" style="display: {delivery_display}; padding: 20px; background: rgba(255,255,255,0.02); border-radius: 20px; border: 0.5px solid var(--glass-border);">
                    <label class="fw-800 text-white mb-3"><i class="fas fa-truck me-2 text-primary"></i> Логістика</label>
                    <div class="row g-3">
                        <div class="col-12"><input name="delivery_address" id="editDelivery" class="glass-input" placeholder="Місто, відділення..."></div>
                        <div class="col-12"><input name="ttn" id="editTtn" class="glass-input" placeholder="ТТН (Номер накладної)"></div>
                        <div class="col-12">
                            <select name="delivery_status" id="editDelStatus" class="form-select">
                                <option value="pending">Очікує відправки</option><option value="sent">Відправлено</option>
                                <option value="delivered">Отримано</option><option value="returned">Відмова / Повернення</option>
                            </select>
                        </div>
                    </div>
                </div>
                
                <div class="col-12"><label class="form-label">Статус</label>
                    <select name="status" id="editStatus" class="form-select">
                        <option value="pending">Очікує підтвердження</option>
                        <option value="confirmed">Очікується</option>
                        <option value="completed">Виконано</option>
                        <option value="cancelled">Скасовано</option>
                    </select>
                </div>
            </div>
        </div><div class="modal-footer d-flex gap-3">
            <button type="button" class="btn-glass flex-grow-1 py-3" onclick="deleteApp()" style="background: rgba(248, 113, 113, 0.1); color: #f87171 !important; border-color: rgba(248, 113, 113, 0.2);"><i class="fas fa-trash me-2"></i>Видалити</button>
            <button class="btn-primary-glow flex-grow-1 m-0 py-3">Зберегти зміни</button>
        </div></form>
      </div></div>
    </div>
    """

    scripts = f"""
    <script>
    const servicesData = {services_json};
    let calendarData = [];
    let currentMonth = new Date().getMonth();
    let currentYear = new Date().getFullYear();
    function formatCalendarMonth() {{
        const label = document.getElementById('calendarMonthYear');
        if (!label) return;
        label.textContent = new Intl.DateTimeFormat(document.documentElement.lang, {{
            month: "long", year: "numeric",
        }}).format(new Date(currentYear, currentMonth, 1));
    }}
    window.addEventListener("safeorbit:language-changed", formatCalendarMonth);
    
    // Lazy Load прапорці (для усунення перерендеру)
    let calendarInitialized = false;
    let chartsInitialized = false;
    
    function updatePrice() {{
        const sel = document.getElementById('serviceSelect');
        const costIn = document.getElementById('costInput');
        const customIn = document.getElementById('customServiceInput');
        if (sel.value === 'custom') {{ customIn.classList.remove('d-none'); customIn.required = true; }}
        else {{ customIn.classList.add('d-none'); customIn.required = false; }}
        const opt = sel.options[sel.selectedIndex];
        const sId = opt.getAttribute('data-id');
        if (sId && servicesData[sId]) {{ costIn.value = servicesData[sId].price; }}
    }}

    function editApp(id, date, time, status, cost, masterId, deliveryAddress, ttn, delStatus) {{
        document.getElementById('editId').value = id;
        document.getElementById('editDate').value = date;
        document.getElementById('editTime').value = time;
        document.getElementById('editStatus').value = status;
        document.getElementById('editCost').value = cost;
        document.getElementById('editMaster').value = masterId;
        let d = document.getElementById('editDelivery'); if(d) d.value = deliveryAddress || '';
        let t = document.getElementById('editTtn'); if(t) t.value = ttn || '';
        let ds = document.getElementById('editDelStatus'); if(ds) ds.value = delStatus || 'pending';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('editModal')).show();
    }}

    async function askAI() {{
        let q = document.getElementById('aiQuestion').value;
        let r = document.getElementById('aiResponse');
        if(!q) return;
        r.innerHTML = '<div class="d-flex align-items-center gap-3"><div class="spinner-border spinner-border-sm text-primary"></div><span>Шукаю відповідь...</span></div>';
        let f = new FormData(); f.append('question', q);
        let res = await fetch('/admin/ask-ai', {{method:'POST', body:f}});
        let data = await res.json(); 
        r.textContent = data.answer;
        r.style.whiteSpace = 'pre-wrap';
    }}

    function startDictation() {{
        if (window.hasOwnProperty('webkitSpeechRecognition')) {{
            var recognition = new webkitSpeechRecognition();
            recognition.continuous = false; recognition.interimResults = false;
            recognition.lang = "uk-UA"; recognition.start();
            recognition.onresult = function(e) {{
                document.getElementById('aiQuestion').value = e.results[0][0].transcript;
                askAI();
            }};
        }}
    }}

    function deleteApp() {{
        Swal.fire({{
            title: 'Видалити запис?',
            text: "Це неможливо буде скасувати!",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#f87171',
            cancelButtonColor: 'rgba(255,255,255,0.1)',
            confirmButtonText: 'Так, видалити',
            cancelButtonText: 'Скасувати',
            background: 'rgba(20, 20, 25, 0.95)',
            color: '#fff'
        }}).then(async (result) => {{
            if (result.isConfirmed) {{
                let id = document.getElementById('editId').value;
                let f = new FormData(); f.append('id', id);
                await fetch('/admin/delete-appointment', {{method:'POST', body:f}});
                window.location.reload();
            }}
        }});
    }}

    function openNotify(phone, date, time) {{
        let msg = `Нагадуємо про ваш візит на ${{date}} о ${{time}}. Чекаємо на вас!`;
        document.getElementById('notifyMsg').value = msg;
        document.getElementById('notifyPhone').value = phone;
        let cleanPhone = phone.replace(/[^0-9]/g, '');
        document.getElementById('btnWa').href = `https://wa.me/${{cleanPhone}}?text=${{encodeURIComponent(msg)}}`;
        document.getElementById('btnViber').href = `viber://chat?number=%2B${{cleanPhone}}`;
        document.getElementById('btnTg').href = `https://t.me/+${{cleanPhone}}`;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('notifyModal')).show();
    }}

    async function sendSMS() {{
        const phone = document.getElementById('notifyPhone').value;
        const msg = document.getElementById('notifyMsg').value;
        const btn = document.getElementById('btnSms');
        const old = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>';
        let f = new FormData(); f.append('phone', phone); f.append('message', msg);
        let res = await fetch('/admin/send-sms', {{method:'POST', body:f}});
        let data = await res.json();
        btn.innerHTML = old;
        showToast(data.msg, data.ok ? 'success' : 'error');
    }}

    async function initCalendar() {{
        if (calendarInitialized) return;
        calendarInitialized = true;
        
        const res = await fetch('/admin/calendar-data');
        calendarData = await res.json();
        renderCalendar();
    }}

    function renderCalendar() {{
        const daysContainer = document.getElementById('calendarDays');
        daysContainer.innerHTML = '';
        
        const date = new Date(currentYear, currentMonth, 1);
        formatCalendarMonth();
        
        let firstDay = date.getDay(); if(firstDay === 0) firstDay = 7;
        for(let i = 1; i < firstDay; i++) {{
            const empty = document.createElement('div');
            empty.className = 'day other-month';
            daysContainer.appendChild(empty);
        }}
        
        const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
        const today = new Date();
        
        for(let i = 1; i <= daysInMonth; i++) {{
            const dayEl = document.createElement('div');
            dayEl.className = 'day';
            dayEl.innerText = i;
            
            const dateStr = `${{currentYear}}-${{String(currentMonth+1).padStart(2,'0')}}-${{String(i).padStart(2,'0')}}`;
            const hasEvent = calendarData.some(e => e.date === dateStr);
            if(hasEvent) dayEl.classList.add('has-event');
            
            if(today.getDate() === i && today.getMonth() === currentMonth && today.getFullYear() === currentYear) {{
                dayEl.classList.add('today');
            }}
            
            dayEl.onclick = () => showDayDetails(dateStr);
            daysContainer.appendChild(dayEl);
        }}
    }}

    async function changeMonth(dir) {{
        currentMonth += dir;
        if(currentMonth < 0) {{ currentMonth = 11; currentYear--; }}
        if(currentMonth > 11) {{ currentMonth = 0; currentYear++; }}
        const start = `${{currentYear}}-${{String(currentMonth+1).padStart(2,'0')}}-01`;
        const following = new Date(currentYear, currentMonth + 1, 1);
        const end = `${{following.getFullYear()}}-${{String(following.getMonth()+1).padStart(2,'0')}}-01`;
        const response = await fetch(`/admin/calendar-data?start=${{start}}&end=${{end}}`);
        calendarData = await response.json();
        renderCalendar();
    }}

    function escapeCalendarText(value) {{
        const element = document.createElement('span');
        element.textContent = String(value ?? '');
        return element.innerHTML;
    }}

    async function showDayDetails(date) {{
        const res = await fetch(`/admin/day-details?date=${{date}}`);
        const data = await res.json();
        let html = `<div class="p-2">`;
        if(data.length === 0) html += `<p class="text-center text-muted py-4">На цей день записів немає</p>`;
        else {{
            data.forEach(a => {{
                html += `
                <div class="glass-card mb-3 p-3" style="border-radius: 20px;">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-800 text-white">${{escapeCalendarText(a.time)}}</span>
                        <span class="badge bg-primary bg-opacity-10 text-primary">${{escapeCalendarText(a.status)}}</span>
                    </div>
                    <div class="fw-700 text-white mb-1">${{escapeCalendarText(a.customer)}}</div>
                    <div class="small text-muted">${{escapeCalendarText(a.service)}}</div>
                </div>`;
            }});
        }}
        html += `</div>`;
        
        Swal.fire({{
            title: `Записи на ${{date}}`,
            html: html,
            showConfirmButton: false,
            background: 'rgba(20, 20, 25, 0.95)',
            color: '#fff',
            customClass: {{ popup: 'glass-card' }}
        }});
    }}

    function initCharts() {{
        if (chartsInitialized) return;
        chartsInitialized = true;
        
        const ctxS = document.getElementById('chartSource').getContext('2d');
        new Chart(ctxS, {{
            type: 'doughnut',
            data: {{
                labels: ['AI Асистент', 'Вручну'],
                datasets: [{{
                    data: [{ai_count}, {manual_count}],
                    backgroundColor: ['#af85ff', 'rgba(255,255,255,0.1)'],
                    borderWidth: 0
                }}]
            }},
            options: {{ plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#fff' }} }} }} }}
        }});

        const ctxServ = document.getElementById('chartServices').getContext('2d');
        new Chart(ctxServ, {{
            type: 'bar',
            data: {{
                labels: {json.dumps([s[0] for s in top_services]).replace("<", "\\u003c")},
                datasets: [{{
                    label: 'Кількість',
                    data: [{", ".join([str(s[1]) for s in top_services])}],
                    backgroundColor: '#60a5fa',
                    borderRadius: 10
                }}]
            }},
            options: {{ 
                scales: {{ 
                    y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#fff' }} }},
                    x: {{ grid: {{ display: false }}, ticks: {{ color: '#fff' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        const ctxLTV = document.getElementById('chartLTV').getContext('2d');
        new Chart(ctxLTV, {{
            type: 'line',
            data: {{
                labels: {json.dumps([c[0] for c in top_clients]).replace("<", "\\u003c")},
                datasets: [{{
                    data: [{", ".join([str(c[2]) for c in top_clients])}],
                    borderColor: '#f472b6',
                    backgroundColor: 'rgba(244, 114, 182, 0.1)',
                    fill: true,
                    tension: 0.4
                }}]
            }},
            options: {{ 
                scales: {{ 
                    y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#fff' }} }},
                    x: {{ grid: {{ display: false }}, ticks: {{ color: '#fff' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
    }}

    document.addEventListener('DOMContentLoaded', () => {{
        const calTab = document.querySelector('[data-bs-target="#tab-calendar"]');
        const analyticsTab = document.querySelector('[data-bs-target="#tab-analytics"]');
        
        // Асинхронний рендер графіків ТІЛЬКИ після повної анімації відкриття вкладки (щоб не лагало)
        if (calTab) {{
            calTab.addEventListener('shown.bs.tab', initCalendar);
            // Якщо вкладка була збережена як активна в localStorage - ініціалізуємо
            if (calTab.classList.contains('active')) initCalendar();
        }}
        if (analyticsTab) {{
            analyticsTab.addEventListener('shown.bs.tab', initCharts);
            if (analyticsTab.classList.contains('active')) initCharts();
        }}
    }});
    </script>
    """
    selected_day = day or now.date()
    if not 1 < selected_day.year < 9999 or period not in {7, 30}:
        raise HTTPException(422, "Invalid overview period")
    agenda_filters = list(filters)
    if specialist:
        if not any(master.id == specialist for master in masters):
            raise HTTPException(404)
        agenda_filters.append(Appointment.master_id == specialist)
    overview = render_template(
        "app/overview.html", business_name=user.business.name if user.business else "SafeOrbit",
        day=selected_day, previous_day=selected_day - timedelta(days=1),
        next_day=selected_day + timedelta(days=1), today=now.date(), specialist=specialist,
        roster=sorted(masters, key=lambda member: member.name.casefold()), period=period,
        can_report=user.role in {"owner", "admin", "manager"},
        **await day_overview(db, user.business_id, agenda_filters, selected_day, period),
    )
    original_heading = '<div class="d-flex flex-column flex-lg-row justify-content-between align-items-start align-items-lg-center mb-5 gap-3">'
    content = content.replace(original_heading, original_heading.replace('mb-5', 'mb-5 overview-legacy-heading'), 1)
    page = overview + '<div id="legacy-workspace-content" hidden>' + content + '</div>'
    enhancement = '<script src="/static/saas/overview.js?v=agenda1" defer></script>'
    rendered = get_layout(page, user, "dash", scripts=scripts + enhancement)
    # Insert feature styling before the final contrast/theme override.
    theme_link = '<link rel="stylesheet" href="/static/v2/theme.css'
    return rendered.replace(theme_link,
        '<link rel="stylesheet" href="/static/v2/overview.css?v=agenda2">' + theme_link, 1)

REPORT_ROLES = {"owner", "admin", "manager"}
REPORT_STATUS = {"completed": "Завершено", "cancelled": "Скасовано",
                 "confirmed": "Підтверджено", "pending": "Очікує підтвердження"}


def report_period(start: date | None, end: date | None):
    today = datetime.now(UA_TZ).date()
    end = end or today
    start = start or end.replace(day=1)
    return start, end


def report_filters(business_id, start, end, specialist=None):
    filters = (
        Appointment.business_id == business_id,
        Appointment.appointment_time >= datetime.combine(start, time.min),
        Appointment.appointment_time <= datetime.combine(end, time.max),
    )
    return filters if specialist is None else (*filters, Appointment.master_id == specialist)


@router.get("/admin/reports", response_class=HTMLResponse)
async def reports_page(
    start: date | None = None, end: date | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
    specialist: Optional[int] = None,
):
    if not user or user.role not in REPORT_ROLES:
        return RedirectResponse("/login" if not user else "/admin", status_code=303)
    specialist = specialist or None
    start, end = report_period(start, end)
    specialists = (await db.execute(select(Master.id, Master.name).where(
        Master.business_id == user.business_id,
    ).order_by(Master.name, Master.id))).all()
    today = datetime.now(UA_TZ).date()
    presets = [
        ("Останні 7 днів", today - timedelta(days=6), today),
        ("Останні 30 днів", today - timedelta(days=29), today),
        ("Цей місяць", today.replace(day=1), today),
    ]
    options = dict(start=start, end=end, specialists=specialists, specialist=specialist, presets=presets)
    if not 0 <= (end - start).days < 366:
        content = render_template("app/reports.html", **options,
                                  error="Оберіть період від 1 до 366 днів.")
        return HTMLResponse(get_layout(content, user, "reports"), status_code=422)

    completed = Appointment.status == "completed"
    count = func.count(Appointment.id)
    filters = report_filters(user.business_id, start, end, specialist)
    result = await db.execute(select(
        Appointment.service_type.label("name"),
        count.label("total"),
        func.sum(case((completed, 1), else_=0)).label("completed"),
        func.sum(case((Appointment.status == "cancelled", 1), else_=0)).label("cancelled"),
        func.sum(case((completed, Appointment.cost), else_=0)).label("revenue"),
       ).where(*filters)
      .group_by(Appointment.service_type)
      .order_by(count.desc(), Appointment.service_type))
    services = result.all()
    revenue = sum(row.revenue or 0 for row in services)
    completed_count = sum(row.completed for row in services)
    day = func.date(Appointment.appointment_time)
    daily_totals = (await db.execute(select(day, func.sum(Appointment.cost)).where(
        *filters, completed,
    ).group_by(day))).all()
    amounts = {str(day_key): amount for day_key, amount in daily_totals}
    span = (end - start).days + 1
    step = 7 if span > 35 else 1
    trend = []
    for offset in range(0, span, step):
        first = start + timedelta(days=offset)
        last = start + timedelta(days=min(offset + step, span) - 1)
        value = sum(amounts.get(str(start + timedelta(days=index)), 0) or 0
                    for index in range(offset, min(offset + step, span)))
        label = first.strftime("%d.%m")
        if first != last:
            label += "–" + last.strftime("%d.%m")
        trend.append((label, value))
    peak = max((value for _, value in trend), default=0) or 1
    team = (await db.execute(select(
        Master.name, count.label("total"),
        func.sum(case((completed, 1), else_=0)).label("completed"),
        func.sum(case((completed, Appointment.cost), else_=0)).label("revenue"),
    ).outerjoin(Master, and_(Appointment.master_id == Master.id, Master.business_id == user.business_id))
      .where(*filters).group_by(Master.id, Master.name)
      .order_by(desc("revenue"), Master.name))).all()
    products = (await db.scalars(select(Product).where(
        Product.business_id == user.business_id, Product.stock <= 5,
    ).order_by(Product.stock, Product.name))).all()
    metrics = [
        ("Записів", sum(row.total for row in services)),
        ("Завершено", completed_count),
        ("Скасовано", sum(row.cancelled for row in services)),
        ("Дохід за завершеними записами", f"{revenue:,.2f} ₴"),
        ("Середня сума завершеного запису", f"{revenue / completed_count if completed_count else 0:,.2f} ₴"),
    ]
    return get_layout(render_template(
        "app/reports.html", **options, metrics=metrics, services=services, stock=products, team=team,
        trend=[(label, value, min(100, max(0, round(100 * value / peak)))) for label, value in trend],
        trend_weekly=step == 7,
    ), user, "reports")


def csv_text(value):
    value = str(value or "")
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


@router.get("/admin/reports/export")
async def export_reports(
    start: date | None = None, end: date | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
    specialist: Optional[int] = None,
):
    if not user or user.role not in REPORT_ROLES:
        raise HTTPException(403, "Експорт доступний власнику, адміністратору або менеджеру.")
    start, end = report_period(start, end)
    if not 0 <= (end - start).days < 366:
        raise HTTPException(422, "Оберіть період від 1 до 366 днів.")
    rows = await db.stream(select(
        Appointment.appointment_time, Appointment.service_type, Appointment.status, Appointment.cost,
        Customer.name, Master.name.label("master"),
    ).outerjoin(Customer, and_(Appointment.customer_id == Customer.id, Customer.business_id == user.business_id))
      .outerjoin(Master, and_(Appointment.master_id == Master.id, Master.business_id == user.business_id))
      .where(*report_filters(user.business_id, start, end, specialist or None))
      .order_by(Appointment.appointment_time, Appointment.id))
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Дата та час", "Послуга", "Статус", "Сума, ₴", "Клієнт", "Спеціаліст"])
    async for row in rows:
        writer.writerow([row.appointment_time.isoformat(sep=" ", timespec="minutes"), csv_text(row.service_type),
                         csv_text(REPORT_STATUS.get(row.status, row.status)), f"{row.cost:.2f}",
                         csv_text(row.name), csv_text(row.master)])
    return Response(
        content=output.getvalue().encode("utf-8-sig"), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="safeorbit-{start}-{end}.csv"',
                 "Cache-Control": "private, no-store"},
    )


@router.post("/admin/add-appointment")
async def add_appointment(
    phone: str = Form(...),
    name: Optional[str] = Form(""),
    date: str = Form(...),
    time: str = Form(...),
    service: str = Form(...),
    custom_service: Optional[str] = Form(""),
    cost: Optional[str] = Form("0.0"),
    master_id: Optional[str] = Form(None),
    delivery_address: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    overview_period: Annotated[Optional[int], Form()] = None,
    overview_specialist: Annotated[int, Form()] = 0,
):
    if not user: return RedirectResponse("/", status_code=303)
    
    if user.role not in {"owner", "admin", "manager", "master"}:
        return RedirectResponse("/admin?error=permission", status_code=303)
    actual_service = custom_service if service == "custom" else service
    try:
        dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        parsed_cost = float(cost or 0)
        parsed_master_id = int(master_id) if master_id and master_id != "None" else None
    except (ValueError, TypeError):
        return RedirectResponse("/admin?error=fields", status_code=303)
    if not actual_service or not phone.strip() or not math.isfinite(parsed_cost) or parsed_cost < 0:
        return RedirectResponse("/admin?error=fields", status_code=303)
    if await personal_schedule(user, db):
        parsed_master_id = user.master_id
    if not await valid_assignment(user, parsed_master_id, db):
        return RedirectResponse("/admin?error=master", status_code=303)
    if await conflicts(db, user.business_id, dt, parsed_master_id, actual_service, published_only=True):
        return RedirectResponse("/admin?error=taken", status_code=303)
    
    customer = await db.scalar(select(Customer).where(and_(Customer.business_id == user.business_id, Customer.phone_number == phone)))
    if not customer:
        customer = Customer(business_id=user.business_id, phone_number=phone, name=name)
        db.add(customer)
        await db.flush()
    elif name and customer.name != name:
        customer.name = name
        
    app = Appointment(
        business_id=user.business_id,
        customer_id=customer.id,
        master_id=parsed_master_id,
        appointment_time=dt,
        service_type=actual_service,
        cost=parsed_cost,
        delivery_address=delivery_address,
        source="manual",
        status="confirmed"
    )
    db.add(app)
    await db.commit()
    await log_action(db, user.business_id, user.id, "Додано запис", f"Запис для {name or phone} на {date} {time}")
    
    return saved_agenda("added", app, overview_period, overview_specialist)

@router.post("/admin/api/update-appointment-time")
async def api_update_appt_time(id: int = Form(...), date: str = Form(...), time: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"ok": False}
    res = await db.execute(select(Appointment).where(and_(Appointment.id == id, Appointment.business_id == user.business_id)))
    appt = res.scalar_one_or_none()
    if appt and await can_manage_appointment(user, appt, db):
        try:
            selected_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            if await conflicts(db, user.business_id, selected_time, appt.master_id, appt.service_type,
                               exclude=appt.id, published_only=True):
                return {"ok": False, "error": "Цей час уже зайнятий."}
            appt.appointment_time = selected_time
            await db.commit()
            return {"ok": True}
        except ValueError: pass
    return RedirectResponse("/admin?msg=saved", status_code=303)

@router.post("/admin/update-appointment")
async def update_appointment(
    id: int = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    cost: Optional[str] = Form("0.0"),
    master_id: Optional[str] = Form(None),
    delivery_address: Optional[str] = Form(None),
    ttn: Optional[str] = Form(None),
    delivery_status: Optional[str] = Form(None),
    status: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    overview_period: Annotated[Optional[int], Form()] = None,
    overview_specialist: Annotated[int, Form()] = 0,
):
    if not user: return RedirectResponse("/", status_code=303)
    app = await db.get(Appointment, id)
    if app and await can_manage_appointment(user, app, db):
        try:
            parsed_cost = float(cost) if cost and str(cost).strip() else 0.0
        except ValueError:
            return RedirectResponse("/admin?error=fields", status_code=303)
            
        parsed_master_id = None
        if master_id and str(master_id).strip() and str(master_id) != 'None':
            try: parsed_master_id = int(master_id)
            except ValueError: return RedirectResponse("/admin?error=fields", status_code=303)

        if not math.isfinite(parsed_cost) or parsed_cost < 0 or status not in {"confirmed", "completed", "cancelled", "pending"}:
            return RedirectResponse("/admin?error=fields", status_code=303)
        if not await valid_assignment(user, parsed_master_id, db):
            return RedirectResponse("/admin?error=master", status_code=303)

        try:
            selected_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return RedirectResponse("/admin?error=fields", status_code=303)
        if status in {"confirmed", "pending"} and await conflicts(db, user.business_id, selected_time, parsed_master_id,
                                                                   app.service_type, exclude=app.id, published_only=True):
            return RedirectResponse("/admin?error=taken", status_code=303)
        app.appointment_time = selected_time
        app.cost, app.master_id, app.delivery_address = parsed_cost, parsed_master_id, delivery_address
        app.ttn, app.delivery_status, app.status = ttn, delivery_status, status
        await db.commit()
        await log_action(db, user.business_id, user.id, "Оновлено запис", f"Запис #{id} оновлено")
        return saved_agenda("saved", app, overview_period, overview_specialist)
    return RedirectResponse("/admin?msg=saved", status_code=303)

@router.post("/admin/delete-appointment")

async def delete_appt(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    
    appt_to_delete = await db.get(Appointment, id)
    if appt_to_delete and await can_manage_appointment(user, appt_to_delete, db):
        customer_id = appt_to_delete.customer_id
        await db.delete(appt_to_delete)
        await log_action(db, user.business_id, user.id, "Видалено запис", f"ID запису: {id}")
        await db.commit()

    return RedirectResponse("/admin?msg=deleted", status_code=303)

@router.get("/admin/receipt/{id}", response_class=HTMLResponse)
async def generate_receipt(id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    appt = await db.get(Appointment, id)
    if not appt or appt.business_id != user.business_id or (
        await personal_schedule(user, db) and appt.master_id != user.master_id
    ):
        return HTMLResponse("Помилка доступу", status_code=403)
    
    biz = await db.get(Business, appt.business_id)
    master = await db.get(Master, appt.master_id) if appt.master_id else None
    customer = await db.get(Customer, appt.customer_id)
    if customer and customer.business_id != appt.business_id:
        customer = None
    if master and master.business_id != appt.business_id:
        master = None
    master_name = master.name if master else "Система"
    delivery_info = f'<div class="d-flex"><span style="white-space:nowrap;margin-right:8px;">Доставка:</span><span class="text-end fw-bold">{html.escape(appt.delivery_address)}</span></div><div class="border-bottom"></div>' if appt.delivery_address else ""
    
    return f"""<!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8">
        <title>Чек #{appt.id}</title>
        <script defer src="/static/locales/catalog.js?v=sale-locales2"></script>
    <script defer src="/static/i18n.js?v=sale-locales2"></script>
        <style>
            body {{ font-family: 'Courier New', Courier, monospace; background: #e5e7eb; display: flex; justify-content: center; padding: 2rem; margin: 0; }}
            .receipt {{ background: white; padding: 2rem; width: 320px; border-radius: 4px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); color: #000; }}
            .text-center {{ text-align: center; }}
            .fw-bold {{ font-weight: 700; }}
            .border-bottom {{ border-bottom: 2px dashed #000; margin: 1rem 0; }}
            .d-flex {{ display: flex; justify-content: space-between; margin-bottom: 0.5rem; font-size: 0.9rem; }}
            @media print {{
                body {{ background: white; padding: 0; }}
                .receipt {{ width: 100%; box-shadow: none; padding: 0; margin: 0; }}
                .no-print {{ display: none !important; }}
            }}
            .btn {{ display: block; width: 100%; background: #4f46e5; color: white; text-align: center; padding: 0.8rem; text-decoration: none; border-radius: 8px; font-family: sans-serif; font-weight: 600; margin-top: 2rem; cursor: pointer; border: none; font-size: 1rem; }}
            .btn:hover {{ background: #4338ca; }}
        </style>
    </head>
    <body>
        <div class="receipt">
            <div class="text-center fw-bold" style="font-size: 1.4rem; margin-bottom: 0.5rem;">{html.escape(biz.name)}</div>
            <div class="text-center" style="font-size: 0.85rem; margin-bottom: 1rem;">{html.escape(biz.address or 'Адреса не вказана')}</div>
            <div class="border-bottom"></div>
            <div class="d-flex"><span>Чек №:</span><span>{appt.id}</span></div>
            <div class="d-flex"><span>Дата:</span><span>{appt.appointment_time.strftime('%d.%m.%Y %H:%M')}</span></div>
            <div class="d-flex"><span>Профіль гостя:</span><span>{html.escape((customer.name if customer else None) or 'Гість')}</span></div>
            <div class="d-flex"><span>Касир:</span><span>{html.escape(master_name)}</span></div>
            <div class="border-bottom"></div>
            {delivery_info}
            <div class="fw-bold mb-2">Послуга:</div>
            <div class="d-flex"><span>{html.escape(appt.service_type)}</span><span>{appt.cost:.2f} грн</span></div>
            <div class="border-bottom"></div>
            <div class="d-flex fw-bold" style="font-size: 1.2rem;"><span>СУМА ДО СПЛАТИ:</span><span>{appt.cost:.2f} грн</span></div>
            <div class="border-bottom"></div>
            <div class="text-center" style="font-size: 0.85rem;">Дякуємо за візит!<br>Чекаємо на вас знову.</div>
            <button class="btn no-print" onclick="window.print()">🖨️ Зберегти PDF / Друк</button>
        </div>
    </body>
    </html>"""

@router.post("/admin/send-sms")
async def send_sms_endpoint(phone: str = Form(...), message: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user:
        return {"ok": False, "msg": "Потрібна авторизація"}
    async with httpx.AsyncClient() as client:
        ok, message = await send_sms(client, user.business, phone, message)
    return {"ok": ok, "msg": message}


@router.get("/admin/api/calendar-events")
async def get_calendar_events(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return []
    
    is_limited_master = await personal_schedule(user, db)

    filters = [Appointment.business_id == user.business_id, Appointment.status != 'cancelled']
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    stmt = select(Appointment).options(joinedload(Appointment.customer.and_(Customer.business_id == user.business_id))).where(and_(*filters))
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    events = []
    for a in appts:
        end_time = a.appointment_time + timedelta(minutes=90)
        color = "#10b981" if a.status == 'completed' else "#4f46e5"
        title = f"{(a.customer.name if a.customer else None) or 'Клієнт'} ({a.service_type})"
        
        events.append({
            "id": a.id, 
            "title": title, 
            "start": a.appointment_time.isoformat(), 
            "end": end_time.isoformat(), 
            "color": color,
            "extendedProps": {
                "id": a.id,
                "status": a.status,
                "cost": a.cost,
                "master_id": str(a.master_id) if a.master_id else "",
                "delivery_address": a.delivery_address or "",
                "ttn": a.ttn or "",
                "delivery_status": a.delivery_status or "pending",
                "date": a.appointment_time.strftime('%Y-%m-%d'),
                "time": a.appointment_time.strftime('%H:%M')
            }
        })
    
    return events

@router.post("/admin/ask-ai")
async def ask_ai(question: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"answer": "Помилка доступу"}
    answer, _ = await process_ai_request(user.business_id, question, db, f"web_{user.id}")
    if not answer: answer = "AI-Асистент тимчасово недоступний або вимкнено в налаштуваннях."
    return {"answer": answer.replace("\n", "<br>")}
