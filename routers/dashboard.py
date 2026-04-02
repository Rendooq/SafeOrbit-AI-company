import json
import html
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, desc, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import LABELS, UA_TZ, DEFAULT_SMS_SENDER
from database import get_db
from dependencies import get_current_user
from models import User, Appointment, Master, Service, Customer, Business, ActionLog, ChatLog
from ui import get_layout
from utils import log_action
from services.ai_service import process_ai_request, get_altegio_free_slots, get_beauty_pro_free_slots
from services.integrations import push_to_beauty_pro, push_to_cleverbox, push_to_integrica, push_to_luckyfit, push_to_uspacy
from services.notifications import send_new_appointment_notifications
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin Panel"])


@router.get("/admin", response_class=HTMLResponse)
async def owner_dash(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "master"]: return RedirectResponse("/", status_code=303)
    
    is_limited_master = False
    if user.role == "master":
        m_record = await db.get(Master, user.master_id)
        if not m_record or m_record.role == "Експерт":
            is_limited_master = True

    now = datetime.now(UA_TZ)
    today_start = now.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    filters = [Appointment.business_id == user.business_id]
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    c_day = await db.scalar(select(func.count(Appointment.id)).where(and_(*filters, Appointment.status != 'cancelled', Appointment.appointment_time >= today_start, Appointment.appointment_time < today_start + timedelta(days=1))))
    c_month = await db.scalar(select(func.count(Appointment.id)).where(and_(*filters, Appointment.status != 'cancelled', Appointment.appointment_time >= month_start)))
    rev_month = await db.scalar(select(func.sum(Appointment.cost)).where(and_(*filters, Appointment.status == 'completed', Appointment.appointment_time >= month_start))) or 0
    rev_total = await db.scalar(select(func.sum(Appointment.cost)).where(and_(*filters, Appointment.status == 'completed'))) or 0

    biz_type = user.business.type if user.business else "barbershop"
    l = LABELS.get(biz_type, LABELS["generic"])

    stmt_status = select(Appointment.status, func.count(Appointment.id)).where(and_(*filters)).group_by(Appointment.status)
    res_status = await db.execute(stmt_status)
    s_map = dict(res_status.all())
    
    masters = (await db.execute(select(Master).where(and_(Master.business_id == user.business_id, Master.is_active == True)))).scalars().all()
    services = (await db.execute(select(Service).where(Service.business_id == user.business_id))).scalars().all()
    services_json = json.dumps({s.id: {'price': s.price, 'name': s.name} for s in services})

    stmt = select(Appointment).options(joinedload(Appointment.customer), joinedload(Appointment.master)).where(and_(*filters)).order_by(desc(Appointment.appointment_time)).limit(10)
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    status_badges = {
        "confirmed": "<span class='badge bg-primary bg-opacity-10 text-primary'>Очікується</span>",
        "completed": "<span class='badge bg-success bg-opacity-10 text-success'>Виконано</span>",
        "cancelled": "<span class='badge bg-danger bg-opacity-10 text-danger'>Скасовано</span>"
    }

    master_options = "".join([f'<option value="{m.id}">{m.name}</option>' for m in masters])
    service_options = "".join([f'<option value="{s.name}" data-id="{s.id}">{s.name} ({s.price} грн)</option>' for s in services])

    ai_count = await db.scalar(select(func.count(Appointment.id)).where(and_(*filters, Appointment.source == 'ai'))) or 0
    manual_count = await db.scalar(select(func.count(Appointment.id)).where(and_(*filters, Appointment.source == 'manual'))) or 0
    
    top_services = (await db.execute(select(Appointment.service_type, func.count(Appointment.id)).where(and_(*filters)).group_by(Appointment.service_type).order_by(desc(func.count(Appointment.id))).limit(5))).all()
    
    top_clients = (await db.execute(
        select(Customer.name, Customer.phone_number, func.count(Appointment.id).label('appts_count'), func.sum(Appointment.cost).label('total_spent'))
        .join(Appointment)
        .where(and_(Customer.business_id == user.business_id, Appointment.status == 'completed'))
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
            <div class="client-avatar d-flex align-items-center justify-content-center fw-bold me-3 flex-shrink-0" style="width: 48px; height: 48px; border-radius: 14px; background: rgba(255,255,255,0.05); color: #fff;">{initials}</div>
            <div class="client-info flex-grow-1 min-w-0">
                <div class="client-name fw-800 text-white break-words overflow-hidden min-w-0" style="font-size: 14px;">{html.escape(name or 'Гість')}</div>
                <div class="client-meta opacity-50 break-words overflow-hidden min-w-0" style="font-size: 11px;">{phone} • {count} візитів</div>
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
                <div class="small text-muted text-truncate break-words overflow-hidden min-w-0" style="max-width: 200px;">{a.customer.phone_number}</div>
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
                <button class="btn-glass btn-sm me-1" onclick="editApp({a.id}, '{d_str}', '{t_str}', '{a.status}', {a.cost}, '{a.master_id or ''}', '{html.escape(a.delivery_address or '')}', '{html.escape(a.ttn or '')}', '{a.delivery_status or 'pending'}')"><i class="fas fa-edit"></i></button>
                <button class="btn-glass btn-sm me-1" onclick="openNotify('{a.customer.phone_number}', '{d_str}', '{t_str}')"><i class="fas fa-bell"></i></button>
                <a href="/admin/receipt/{a.id}" target="_blank" class="btn-glass btn-sm"><i class="fas fa-print"></i></a>
            </td>
        </tr>
        """

    stmt_broadcast = select(ActionLog).where(ActionLog.action == 'Розсилка').order_by(desc(ActionLog.created_at)).limit(1)
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
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="tab" data-bs-target="#tab-calendar" onclick="initCalendar()"><i class="fas fa-calendar-days me-2"></i>Календар</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="tab" data-bs-target="#tab-analytics" onclick="initCharts()"><i class="fas fa-chart-pie me-2"></i>Аналітика</button></li>
        </ul>
    </div>

    <div class="tab-content">
        <div class="tab-pane fade show active" id="tab-list">
            <div class="row g-4 mb-4">
                <div class="col-lg-8 col-md-12">
                    <div class="glass-card">
                        <div class="d-flex justify-content-between align-items-center mb-4">
                            <h5 class="fw-800 text-white m-0">{l['new_appt']}</h5>
                            <a href="/widget/{user.business_id}" target="_blank" class="btn-glass py-2" style="font-size: 12px;"><i class="fas fa-external-link-alt me-2"></i>Віджет</a>
                        </div>
                        <form action="/admin/add-appointment" method="post" class="row g-4 max-w-full">
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
                <div class="table-responsive">
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
                            {top_clients_html if top_clients_html else '<div class="text-center p-5 text-muted small border-dashed rounded-4" style="border: 1px dashed rgba(255,255,255,0.1);">Дані збираються...</div>'}
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
    
    <button class="btn-primary-glow rounded-circle d-flex align-items-center justify-content-center" style="position:fixed;bottom:30px;right:30px;width:64px;height:64px;z-index:1000; border:none;" onclick="new bootstrap.Modal(document.getElementById('aiModal')).show()">
        <i class="fas fa-robot fa-xl"></i>
    </button>

    <div class="modal fade" id="aiModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h5 class="modal-title">AI Асистент</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <div class="modal-body">
            <div id="aiResponse" class="mb-4 p-4 rounded-4" style="background: rgba(255,255,255,0.02); min-height: 100px; color: rgba(255,255,255,0.8); font-size: 14px; border: 0.5px solid var(--glass-border); line-height: 1.6;">Запитайте щось про ваші записи...</div>
            <div class="input-group gap-2">
                <input id="aiQuestion" class="glass-input break-words overflow-hidden min-w-0" placeholder="Хто записаний на завтра?">
                <button class="btn-glass px-3" onclick="startDictation()"><i class="fas fa-microphone"></i></button>
                <button class="btn-primary-glow px-4" onclick="askAI()"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>
    </div></div></div>

    <div class="modal fade" id="notifyModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h5 class="modal-title">Надіслати нагадування</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <div class="modal-body">
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
      <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h5 class="modal-title">Редагування Запису</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/admin/update-appointment" method="post"><div class="modal-body">
            <input type="hidden" name="id" id="editId">
            <div class="row g-3">
                <div class="col-md-6"><label class="form-label">Дата</label><input name="date" type="date" id="editDate" class="glass-input" required></div>
                <div class="col-md-6"><label class="form-label">Час</label><input name="time" type="time" id="editTime" class="glass-input" required></div>
                <div class="col-md-12"><label class="form-label">Сума (грн)</label><input name="cost" type="number" step="0.01" id="editCost" class="glass-input"></div>
                <div class="col-md-12"><label class="form-label">{l['master_single']}</label><select name="master_id" id="editMaster" class="form-select">{master_options}</select></div>
                
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
        new bootstrap.Modal(document.getElementById('editModal')).show();
    }}

    async function askAI() {{
        let q = document.getElementById('aiQuestion').value;
        let r = document.getElementById('aiResponse');
        if(!q) return;
        r.innerHTML = '<div class="d-flex align-items-center gap-3"><div class="spinner-border spinner-border-sm text-primary"></div><span>Шукаю відповідь...</span></div>';
        let f = new FormData(); f.append('question', q);
        let res = await fetch('/admin/ask-ai', {{method:'POST', body:f}});
        let data = await res.json(); 
        r.innerHTML = data.answer.replace(/\\n/g, '<br>');
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
        new bootstrap.Modal(document.getElementById('notifyModal')).show();
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
        const res = await fetch('/admin/calendar-data');
        calendarData = await res.json();
        renderCalendar();
    }}

    function renderCalendar() {{
        const daysContainer = document.getElementById('calendarDays');
        const monthYearLabel = document.getElementById('calendarMonthYear');
        daysContainer.innerHTML = '';
        
        const date = new Date(currentYear, currentMonth, 1);
        const monthNames = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"];
        monthYearLabel.innerText = `${{monthNames[currentMonth]}} ${{currentYear}}`;
        
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

    function changeMonth(dir) {{
        currentMonth += dir;
        if(currentMonth < 0) {{ currentMonth = 11; currentYear--; }}
        if(currentMonth > 11) {{ currentMonth = 0; currentYear++; }}
        renderCalendar();
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
                        <span class="fw-800 text-white">${{a.time}}</span>
                        <span class="badge bg-primary bg-opacity-10 text-primary">${{a.status}}</span>
                    </div>
                    <div class="fw-700 text-white mb-1">${{a.customer}}</div>
                    <div class="small text-muted">${{a.service}}</div>
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
                labels: [{", ".join([f"'{s[0]}'" for s in top_services])}],
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
                labels: [{", ".join([f"'{c[0]}'" for c in top_clients])}],
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
        if(window.location.hash === '#calendar') {{
            bootstrap.Tab.getOrCreateInstance(document.querySelector('[data-bs-target="#tab-calendar"]')).show();
            initCalendar();
        }}
    }});
    </script>
    """
    return get_layout(content, user, "dash", scripts=scripts)

@router.post("/api/update-appointment-time")
async def api_update_appt_time(id: int = Form(...), date: str = Form(...), time: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"ok": False}
    res = await db.execute(select(Appointment).where(and_(Appointment.id == id, Appointment.business_id == user.business_id)))
    appt = res.scalar_one_or_none()
    if appt:
        try:
            appt.appointment_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            await db.commit()
            return {"ok": True}
        except ValueError: pass
    return RedirectResponse("/admin?msg=saved", status_code=303)

@router.post("/delete-appointment")
async def delete_appt(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    
    appt_to_delete = await db.get(Appointment, id)
    if appt_to_delete and appt_to_delete.business_id == user.business_id:
        customer_id = appt_to_delete.customer_id
        await db.delete(appt_to_delete)
        await log_action(db, user.business_id, user.id, "Видалено запис", f"ID запису: {id}")
        await db.commit()

    return RedirectResponse("/admin?msg=deleted", status_code=303)

@router.get("/receipt/{id}", response_class=HTMLResponse)
async def generate_receipt(id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    appt = await db.get(Appointment, id)
    if not appt or appt.business_id != user.business_id:
        return HTMLResponse("Помилка доступу", status_code=403)
    
    biz = await db.get(Business, appt.business_id)
    master = await db.get(Master, appt.master_id) if appt.master_id else None
    customer = await db.get(Customer, appt.customer_id)
    master_name = master.name if master else "Система"
    delivery_info = f'<div class="d-flex"><span style="white-space:nowrap;margin-right:8px;">Доставка:</span><span class="text-end fw-bold">{html.escape(appt.delivery_address)}</span></div><div class="border-bottom"></div>' if appt.delivery_address else ""
    
    return f"""<!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8">
        <title>Чек #{appt.id}</title>
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
            <div class="d-flex"><span>Профіль гостя:</span><span>{html.escape(customer.name or 'Гість')}</span></div>
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

@router.post("/send-sms")
async def send_sms_endpoint(phone: str = Form(...), message: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"ok": False, "msg": "Потрібна авторизація"}
    
    biz = await db.get(Business, user.business_id)
    sender = biz.sms_sender_id or DEFAULT_SMS_SENDER
    token = biz.sms_token

    if not token:
        return {"ok": False, "msg": "Помилка: Не вказано SMS токен в налаштуваннях!"}

    url = "https://api.turbosms.ua/message/send.json"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "recipients": [phone],
        "sms": {
            "sender": sender,
            "text": message
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            data = resp.json()
            
            # Перевірка успішності (TurboSMS повертає response_code: 0 або список результатів)
            if data.get("response_code") == 0 or (data.get("response_result") and data["response_result"][0].get("response_code") == 0):
                 return {"ok": True, "msg": "SMS успішно відправлено!"}
            else:
                 error_msg = data.get("response_status") or (data.get("response_result") and data["response_result"][0].get("response_status")) or "Невідома помилка"
                 return {"ok": False, "msg": f"Помилка провайдера: {error_msg}"}
        except Exception as e:
            logger.error(f"SMS Error: {e}")
            return {"ok": False, "msg": f"Помилка мережі: {str(e)}"}

@router.get("/api/calendar-events")
async def get_calendar_events(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return []
    
    is_limited_master = False
    if user.role == "master":
        m_record = await db.get(Master, user.master_id)
        if not m_record or m_record.role == "Експерт":
            is_limited_master = True

    filters = [Appointment.business_id == user.business_id, Appointment.status != 'cancelled']
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    stmt = select(Appointment).options(joinedload(Appointment.customer)).where(and_(*filters))
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    events = []
    for a in appts:
        end_time = a.appointment_time + timedelta(minutes=90)
        color = "#10b981" if a.status == 'completed' else "#4f46e5"
        title = f"{a.customer.name or 'Клієнт'} ({a.service_type})"
        
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

@router.post("/ask-ai")
async def ask_ai(question: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"answer": "Помилка доступу"}
    answer, _ = await process_ai_request(user.business_id, question, db, f"web_{user.id}")
    if not answer: answer = "AI-Асистент тимчасово недоступний або вимкнено в налаштуваннях."
    return {"answer": answer.replace("\n", "<br>")}


@router.post("/api/update-appointment-time")
async def api_update_appt_time(id: int = Form(...), date: str = Form(...), time: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"ok": False}
    res = await db.execute(select(Appointment).where(and_(Appointment.id == id, Appointment.business_id == user.business_id)))
    appt = res.scalar_one_or_none()
    if appt:
        try:
            appt.appointment_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            await db.commit()
            return {"ok": True}
        except ValueError: pass
    return RedirectResponse("/admin?msg=saved", status_code=303)

@router.post("/delete-appointment")
async def delete_appt(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    
    appt_to_delete = await db.get(Appointment, id)
    if appt_to_delete and appt_to_delete.business_id == user.business_id:
        customer_id = appt_to_delete.customer_id
        await db.delete(appt_to_delete)
        await log_action(db, user.business_id, user.id, "Видалено запис", f"ID запису: {id}")
        await db.commit()

    return RedirectResponse("/admin?msg=deleted", status_code=303)

@router.get("/receipt/{id}", response_class=HTMLResponse)
async def generate_receipt(id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    appt = await db.get(Appointment, id)
    if not appt or appt.business_id != user.business_id:
        return HTMLResponse("Помилка доступу", status_code=403)
    
    biz = await db.get(Business, appt.business_id)
    master = await db.get(Master, appt.master_id) if appt.master_id else None
    customer = await db.get(Customer, appt.customer_id)
    master_name = master.name if master else "Система"
    delivery_info = f'<div class="d-flex"><span style="white-space:nowrap;margin-right:8px;">Доставка:</span><span class="text-end fw-bold">{html.escape(appt.delivery_address)}</span></div><div class="border-bottom"></div>' if appt.delivery_address else ""
    
    return f"""<!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8">
        <title>Чек #{appt.id}</title>
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
            <div class="d-flex"><span>Профіль гостя:</span><span>{html.escape(customer.name or 'Гість')}</span></div>
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

@router.post("/send-sms")
async def send_sms_endpoint(phone: str = Form(...), message: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"ok": False, "msg": "Потрібна авторизація"}
    
    biz = await db.get(Business, user.business_id)
    sender = biz.sms_sender_id or DEFAULT_SMS_SENDER
    token = biz.sms_token

    if not token:
        return {"ok": False, "msg": "Помилка: Не вказано SMS токен в налаштуваннях!"}

    url = "https://api.turbosms.ua/message/send.json"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "recipients": [phone],
        "sms": {
            "sender": sender,
            "text": message
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            data = resp.json()
            
            # Перевірка успішності (TurboSMS повертає response_code: 0 або список результатів)
            if data.get("response_code") == 0 or (data.get("response_result") and data["response_result"][0].get("response_code") == 0):
                 return {"ok": True, "msg": "SMS успішно відправлено!"}
            else:
                 error_msg = data.get("response_status") or (data.get("response_result") and data["response_result"][0].get("response_status")) or "Невідома помилка"
                 return {"ok": False, "msg": f"Помилка провайдера: {error_msg}"}
        except Exception as e:
            logger.error(f"SMS Error: {e}")
            return {"ok": False, "msg": f"Помилка мережі: {str(e)}"}

@router.get("/api/calendar-events")
async def get_calendar_events(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return []
    
    is_limited_master = False
    if user.role == "master":
        m_record = await db.get(Master, user.master_id)
        if not m_record or m_record.role == "Експерт":
            is_limited_master = True

    filters = [Appointment.business_id == user.business_id, Appointment.status != 'cancelled']
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    stmt = select(Appointment).options(joinedload(Appointment.customer)).where(and_(*filters))
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    events = []
    for a in appts:
        end_time = a.appointment_time + timedelta(minutes=90)
        color = "#10b981" if a.status == 'completed' else "#4f46e5"
        title = f"{a.customer.name or 'Клієнт'} ({a.service_type})"
        
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

@router.post("/ask-ai")
async def ask_ai(question: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"answer": "Помилка доступу"}
    answer, _ = await process_ai_request(user.business_id, question, db, f"web_{user.id}")
    if not answer: answer = "AI-Асистент тимчасово недоступний або вимкнено в налаштуваннях."
    return {"answer": answer.replace("\n", "<br>")}
