import html
import hmac
import hashlib
from config import SECRET_KEY
from utils.network import validate_public_url
import io
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import urllib.parse, secrets

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from config import LABELS, UA_TZ
from database import get_db
from dependencies import get_current_user
from models import (ActionLog, Appointment, AppointmentConfirmation, Business, ChatLog, Customer,
                    CustomerSegment, GlobalPaymentSettings, Master, MasterService,
                    MonthlyPaymentLog, NPSReview, Product, Service, User, SystemUpdate, Integration, ApiKey, ApiRequestLog)
from ui import get_layout
from utils.logger import log_action
from utils.auth import ROOT, MAX_UPLOAD_BYTES
from utils.security import hash_password, generate_api_key

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/settings", response_class=HTMLResponse)
async def ai_settings_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager", "master"]: return RedirectResponse("/", status_code=303)
    biz = (await db.execute(select(Business).where(Business.id == user.business_id))).scalar_one_or_none()
    
    models = [("llama-3.3-70b-versatile", "AI-5.0.0-expert-version")]
    model_options = "".join([f'<option value="{m[0]}" {"selected" if biz.ai_model == m[0] else ""}>{m[1]}</option>' for m in models])

    masters = (await db.execute(select(Master).options(selectinload(Master.services)).where(Master.business_id == user.business_id))).scalars().all()
    services = (await db.execute(select(Service).where(Service.business_id == user.business_id))).scalars().all()

    master_users = (await db.execute(select(User).where(and_(User.business_id == user.business_id, User.role == 'master')))).scalars().all()
    master_user_map = {u.master_id: u.username for u in master_users if u.master_id}

    l = LABELS.get(biz.type, LABELS["generic"])
    if biz.type == 'school':
        l = {"clients": "Учні", "masters": "Викладачі", "master_single": "Викладач", "services": "Курси", "service_single": "Курс", "appts": "Записи на курси", "new_appt": "Новий учень", "analytics_clients": "Топ Учнів"}
        branch_label = "Філії / Групи"
    else:
        l = LABELS.get(biz.type, LABELS.get("generic", {"clients": "Клієнти"}))
        branch_label = "Філії"

    email_chk = "checked" if biz.email_notifications_enabled else ""
    tg_chk = "checked" if biz.telegram_notifications_enabled else ""

    emails = [e.strip() for e in biz.notification_email.split(',') if e.strip()] if biz.notification_email else [""]
    email_inputs_html = ""
    for email in emails:
        email_inputs_html += f"""<div class="input-group mb-2">
            <input name="email" type="email" class="glass-input" value="{html.escape(email)}" placeholder="example@email.com" style="border-radius: 12px 0 0 12px;">
            <button class="btn btn-glass" type="button" onclick="this.parentElement.remove()" style="border-radius: 0 12px 12px 0;"><i class="fas fa-times text-danger"></i></button>
        </div>"""

    tg_chat_ids = [cid.strip() for cid in biz.telegram_notification_chat_id.split(',') if cid.strip()] if biz.telegram_notification_chat_id else [""]
    tg_chat_id_inputs_html = ""
    for chat_id in tg_chat_ids:
        tg_chat_id_inputs_html += f"""<div class="input-group mb-2">
            <input name="tg_chat_id" class="glass-input" value="{html.escape(chat_id)}" placeholder="Наприклад: -100123456789" style="border-radius: 12px 0 0 12px;">
            <button class="btn btn-glass" type="button" onclick="this.parentElement.remove()" style="border-radius: 0 12px 12px 0;"><i class="fas fa-times text-danger"></i></button>
        </div>"""

    if user.role == "master":
        master = await db.get(Master, user.master_id)
        
        base_url = str(request.base_url).rstrip('/')
        if base_url.startswith("http://"): base_url = base_url.replace("http://", "https://")
        webhook_url = f"{base_url}/webhook/telegram/master/{master.id}"
        
        content = f"""
        <div class="glass-card p-5" style="max-width: 600px; margin: 40px auto;">
            <div class="text-center mb-5">
                <div class="logo-icon mb-3" style="width: 64px; height: 64px; margin: 0 auto; background: rgba(175, 133, 255, 0.1); color: var(--accent-primary); font-size: 28px;"><i class="fas fa-user-circle"></i></div>
                <h4 class="fw-800 text-white">Мій Профіль</h4>
                <p class="text-muted small">Керування особистими налаштуваннями</p>
            </div>
            
            <form action="/admin/update-master-profile" method="post">
                <div class="mb-4">
                    <label class="form-label text-white">Ім'я</label>
                    <input type="text" class="glass-input opacity-50" value="{html.escape(master.name)}" disabled>
                </div>
                <div class="mb-4">
                    <label class="form-label text-white">Токен особистого бота</label>
                    <input name="bot_token" class="glass-input" value="{html.escape(master.personal_bot_token or '')}" placeholder="123456:ABC-DEF...">
                    <div class="small mt-3 opacity-50"><i class="fas fa-circle-info me-2"></i>Створіть бота в <a href="https://t.me/BotFather" target="_blank" class="text-white">@BotFather</a>. Він відповідатиме на ваші питання (напр. "Який графік?").</div>
                    <div class="mt-3 p-2 rounded-3" style="background: rgba(0,0,0,0.2); border: 0.5px solid var(--glass-border);"><code style="font-size: 11px; color: var(--accent-primary);">{webhook_url}</code></div>
                </div>
                <div class="mb-5">
                    <label class="form-label text-white">Новий пароль</label>
                    <input name="new_password" type="password" class="glass-input" placeholder="Залиште пустим, щоб не змінювати">
                </div>
                <button class="btn-primary-glow w-100 py-3">Зберегти налаштування</button>
            </form>
        </div>
        """
        return get_layout(content, user, "set")

    masters_html = ""
    
    reviews = (await db.execute(select(NPSReview).options(joinedload(NPSReview.appointment)).where(NPSReview.business_id == user.business_id))).scalars().all()
    master_ratings = {}
    master_review_counts = {}
    for r in reviews:
        if r.appointment and r.appointment.master_id:
            m_id = r.appointment.master_id
            master_ratings[m_id] = master_ratings.get(m_id, 0) + r.rating
            master_review_counts[m_id] = master_review_counts.get(m_id, 0) + 1
            
    for m in masters:
        avg_rating = round(master_ratings[m.id] / master_review_counts[m.id], 1) if master_review_counts.get(m.id) else 0
        count = master_review_counts.get(m.id, 0)
        rating_html = f'<span class="badge bg-warning text-dark ms-2" title="Кількість відгуків: {count}"><i class="fas fa-star me-1" style="font-size:10px;"></i>{avg_rating}</span>' if count > 0 else '<span class="badge bg-secondary ms-2" style="opacity:0.5;" title="Немає відгуків"><i class="fas fa-star me-1" style="font-size:10px;"></i>-</span>'
        
        acc_btn = ""
        if m.id in master_user_map:
            acc_btn = f'<span class="badge bg-success ms-2" title="Логін: {html.escape(master_user_map[m.id])}"><i class="fas fa-user-check"></i></span>'
        else:
            acc_btn = f'<button type="button" class="btn btn-glass btn-sm ms-2" onclick="createMasterAccount({m.id}, \'{html.escape(m.name, quote=True)}\')" title="Створити акаунт"><i class="fas fa-user-plus text-primary"></i></button>'
            
        masters_html += f"""<li class='list-group-item bg-transparent border-0 d-flex justify-content-between align-items-center mb-3 glass-card p-3'>
            <div><strong class="text-white">{html.escape(m.name)}</strong> {rating_html} <span class="badge bg-primary-glow ms-1" style="font-size: 0.7em;">{html.escape(m.role or 'Майстер')}</span>{acc_btn}<br><small class='text-muted'>{html.escape(', '.join([s.name for s in m.services]))}</small><br><small class="text-info opacity-75"><i class="fas fa-clock me-1"></i> {html.escape(m.working_hours or 'Загальний графік')}</small></div> 
            <form action='/admin/delete-master' method='post' style='display:inline'>
                <input type='hidden' name='id' value='{m.id}'><button class='btn btn-glass btn-sm'><i class="fas fa-times text-danger"></i></button>
            </form>
        </li>"""

    services_checkboxes = "".join([f'<div class="form-check form-switch mb-2"><input class="form-check-input" type="checkbox" name="services" value="{s.id}" id="s{s.id}"><label class="form-check-label text-white small" for="s{s.id}">{s.name}</label></div>' for s in services])
    services_html = "".join([f"<li class='list-group-item bg-transparent border-0 d-flex justify-content-between align-items-center mb-3 glass-card p-3'><div><strong class='text-white'>{html.escape(s.name)}</strong> <small class='text-muted'>({s.price} грн, {s.duration} хв)</small></div> <form action='/admin/delete-service' method='post' style='display:inline'><input type='hidden' name='id' value='{s.id}'><button class='btn btn-glass btn-sm'><i class='fas fa-times text-danger'></i></button></form></li>" for s in services])

    branches_tab_btn = ""
    branches_tab_content = ""
    if biz.parent_id is None:
        branches = (await db.execute(select(Business).where(Business.parent_id == user.business_id))).scalars().all()
        branch_ids = [b.id for b in branches]
        branch_owners = []
        if branch_ids:
            branch_owners = (await db.execute(select(User).where(and_(User.business_id.in_(branch_ids), User.role == 'owner')))).scalars().all()

        branches_html = ""
        for br in branches:
            b_owner = next((u for u in branch_owners if u.business_id == br.id), None)
            login_info = f"Логін: {html.escape(b_owner.username)}" if b_owner else "Немає акаунту"
            switch_btn = f"<a href='/admin/switch-to-branch/{br.id}' class='btn btn-glass btn-sm me-2' title='Увійти в кабінет філії'><i class='fas fa-sign-in-alt me-1 text-success'></i>Увійти</a>" if b_owner else ""
            branches_html += f"""<li class='list-group-item bg-transparent border-0 d-flex justify-content-between align-items-center mb-3 glass-card p-3'>
                <div>
                    <strong class="text-white">{html.escape(br.name)}</strong> 
                    <span class="badge bg-info bg-opacity-10 text-info ms-2">{html.escape(br.city or '')}</span><br>
                    <small class='text-muted'><i class="fas fa-map-marker-alt me-1"></i> {html.escape(br.address or '')}</small><br>
                    <small class='text-primary-glow'><i class="fas fa-user me-1"></i> {login_info}</small>
                </div>
                <div>
                    {switch_btn}
                    <form action='/admin/delete-branch' method='post' style='display:inline' onsubmit="return confirm('Видалити філію та всі її дані?');">
                        <input type='hidden' name='id' value='{br.id}'>
                        <button class='btn btn-glass btn-sm'><i class="fas fa-trash text-danger"></i></button>
                    </form>
                </div>
            </li>"""
        if not branches_html:
            branches_html = "<li class='list-group-item bg-transparent border-0 text-muted text-center py-4'>У вас ще немає філій</li>"

        branches_tab_btn = '<li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-branches">🏢 Філії</button></li>'
        branches_tab_btn = f'<li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-branches">🏢 {branch_label}</button></li>'
        branches_tab_content = f"""
        <div class="tab-pane fade" id="pills-branches">
            <div class="row g-4"> 
                <div class="col-md-5"> 
                    <div class="glass-card p-4">
                        <h5 class="fw-800 text-white mb-4">Додати філію</h5>
                        <h5 class="fw-800 text-white mb-4">Додати {branch_label.split(' / ')[0].lower()}</h5>
                        <form action="/admin/add-branch" method="post">
                            <div class="mb-3"><input name="name" class="glass-input" placeholder="Назва філії (напр. 'На Подолі')" required></div>
                            <div class="mb-3"><input name="name" class="glass-input" placeholder="Назва філії / групи" required></div>
                            <div class="mb-3"><input name="city" class="glass-input" placeholder="Місто (напр. Київ)" required></div>
                            <div class="mb-4"><input name="address" class="glass-input" placeholder="Адреса (напр. вул. Хрещатик, 1)" required></div>
                            <h6 class="fw-800 text-muted small mb-3">Акаунт для входу у філію</h6>
                            <h6 class="fw-800 text-muted small mb-3">Акаунт для входу (менеджер)</h6>
                            <div class="mb-3"><input name="login" class="glass-input" placeholder="Логін (телефон філії)" required></div>
                            <div class="mb-4"><input name="password" type="password" class="glass-input" placeholder="Пароль" required></div>
                            <button class="btn-primary-glow w-100 py-3">Створити філію</button>
                            <button class="btn-primary-glow w-100 py-3">Створити під-акаунт</button>
                        </form>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="glass-card p-4">
                        <h5 class="fw-800 text-white mb-4">Список ваших філій</h5>
                        <ul class="list-group list-group-flush bg-transparent">{branches_html}</ul>
                    </div>
                </div>
            </div>
        </div>"""
        
    # API Tab HTML
    api_keys = (await db.execute(select(ApiKey).where(ApiKey.business_id == user.business_id).order_by(desc(ApiKey.created_at)))).scalars().all()
    api_keys_html = ""
    if not api_keys:
        api_keys_html = "<p class='text-muted small'>API ключі ще не створено.</p>"
    else:
        api_keys_html = "<ul class='list-group list-group-flush bg-transparent'>"
        for key in api_keys:
            last_used = key.last_used_at.strftime('%d.%m.%Y %H:%M') if key.last_used_at else 'Ніколи'
            status_badge = f"<span class='badge bg-success'>Активний</span>" if key.is_active else f"<span class='badge bg-secondary text-white-50'>Вимкнений</span>"
            toggle_icon = "fa-toggle-on text-success" if key.is_active else "fa-toggle-off text-muted"
            toggle_title = "Вимкнути ключ" if key.is_active else "Увімкнути ключ"
            
            api_keys_html += f"""<li class='list-group-item bg-transparent border-0 d-flex justify-content-between align-items-center px-0 mb-3'>
                <div class="flex-grow-1 me-3">
                    <strong class='text-white'>{html.escape(key.name)}</strong> {status_badge}<br>
                    <div class="input-group mt-2">
                        <input type="password" class="glass-input" value="{html.escape(key.api_key or '')}" readonly id="apiKeyInput_{key.id}" style="border-radius: 12px 0 0 12px;">
                        <button class="btn btn-glass icon-btn" type="button" onclick="toggleApiKeyVisibility('apiKeyInput_{key.id}', this)" style="border-radius: 0; border-left: none; border-right: none;" title="Показати/Приховати ключ"><i class="fas fa-eye text-info"></i></button>
                        <button class="btn btn-glass icon-btn" type="button" onclick="copyApiKey('apiKeyInput_{key.id}')" style="border-radius: 0 12px 12px 0;" title="Скопіювати ключ"><i class="fas fa-copy text-success"></i></button>
                    </div>
                    <div class="d-flex justify-content-between align-items-center mt-2">
                        <small class='text-muted'>Останнє використання: {last_used}</small>
                        <button class="btn btn-sm btn-link text-info text-decoration-none p-0" onclick="showApiKeyLogs({key.id}, '{html.escape(key.name)}')"><i class="fas fa-history me-1"></i>Історія запитів</button>
                    </div>
                </div>
                <div class='d-flex flex-column gap-2'>
                    <form action='/admin/toggle-api-key' method='post' style='margin:0;'>
                        <input type='hidden' name='id' value='{key.id}'>
                        <button class='btn btn-glass btn-sm w-100' title='{toggle_title}'><i class="fas {toggle_icon} fa-lg"></i></button>
                    </form>
                    <form action='/admin/delete-api-key' method='post' style='margin:0;' onsubmit="return confirm('Ви впевнені, що хочете ВИДАЛИТИ цей API ключ назавжди?');">
                        <input type='hidden' name='id' value='{key.id}'>
                        <button class='btn btn-glass btn-sm w-100' title='Видалити ключ'><i class="fas fa-trash text-danger"></i></button>
                    </form>
                </div>
            </li>"""
        api_keys_html += "</ul>"

    api_tab_btn = '<li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-api"><i class="fas fa-code me-2"></i>API</button></li>'
    api_tab_content = f"""
        <div class="tab-pane fade" id="pills-api">
            <div class="glass-card p-4 p-md-5" style="max-width: 800px;">
                <h5 class="fw-800 text-white mb-4">REST API для розробників</h5>
                <p class="small text-muted mb-4">Керуйте API ключами для інтеграції вашої CRM з іншими сервісами. Повна документація доступна за посиланням <a href="/api-docs" target="_blank" class="text-info">документація</a>.</p>
                <div class="mb-4">
                    <h6 class="fw-bold text-white mb-3">Ваші ключі</h6>
                    {api_keys_html if api_keys else "<p class='text-muted small mb-4'>API ключі ще не створено. Створіть перший ключ нижче.</p>"}
                </div>
                <form action="/admin/create-api-key" method="post" class="d-flex flex-wrap gap-2 align-items-center">
                    <input type="text" name="name" class="glass-input m-0 flex-grow-1" placeholder="Назва ключа (напр. 'Мій сайт')" required style="max-width: 300px;">
                    <button type="submit" class="btn-primary-glow px-4 py-2 m-0" style="min-height: 44px;"><i class="fas fa-plus me-2"></i>Створити API ключ</button>
                </form>
            </div>
        </div>"""

    if biz.type == 'retail':
        roles_html = """
            <option value="Менеджер з продажу">Менеджер з продажу (обробка замовлень)</option>
            <option value="Кур'єр">Кур'єр (доставка)</option>
            <option value="Пакувальник">Пакувальник (склад)</option>
            <option value="Адміністратор">Адміністратор (бачить всі замовлення)</option>
            <option value="Маркетолог">Маркетолог (аналітика та ШІ)</option>
            <option value="СЕО">СЕО (повний доступ)</option>
            <option value="СОО">СОО (повний доступ)</option>
        """
    elif biz.type == 'school':
        roles_html = f"""
            <option value="Викладач">Викладач (бачить тільки свої групи/записи)</option>
            <option value="Адміністратор">Адміністратор (бачить всі записи)</option>
            <option value="Куратор">Куратор курсу</option>
            <option value="Директор">Директор (повний доступ)</option>
        """
    else:
        roles_html = f"""
            <option value="{l.get('master_single', 'Майстер')}">{l.get('master_single', 'Майстер')} (бачить тільки свої записи)</option>
            <option value="Адміністратор">Адміністратор (бачить всі записи)</option>
            <option value="Маркетолог">Маркетолог (аналітика та ШІ)</option>
            <option value="СЕО">СЕО (повний доступ)</option>
            <option value="СОО">СОО (повний доступ)</option>
        """

    content = f"""
    <div class="glass-card mb-4 p-2 d-inline-flex">
        <ul class="nav nav-pills" id="pills-tab" role="tablist" style="gap: 8px;">
            <li class="nav-item"><button class="nav-link active rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-ai">🤖 ШІ Асистент</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-masters">{l['masters']}</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-services">{l['services']}</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-notifications">🔔 Сповіщення</button></li>
            {branches_tab_btn}
            {api_tab_btn}
        </ul>
    </div>
    
    <div class="tab-content">
        <div class="tab-pane fade show active" id="pills-ai">
            <div class="glass-card p-4 p-md-5" style="max-width: 800px;">
                <form onsubmit="saveForm(event, '/admin/save-prompt')">
                    <div class="row g-3 mb-4">
                        <div class="col-md-6"><label class="form-label text-white">Модель ШІ</label><select name="model" class="form-select">{model_options}</select></div>
                        <div class="col-md-3"><label class="form-label text-white">Температура</label><input name="temp" type="number" step="0.1" min="0" max="1" class="glass-input" value="{biz.ai_temperature}"></div>
                        <div class="col-md-3"><label class="form-label text-white">Макс. токенів</label><input name="tokens" type="number" class="glass-input" value="{biz.ai_max_tokens}"></div>
                    </div>
                    <div class="mb-4">
                        <label class="form-label text-white">Графік роботи (для ШІ)</label>
                        <div class="input-group mb-2" style="background: rgba(255,255,255,0.02); border: 0.5px solid var(--glass-border); border-radius: 18px; padding: 4px;">
                            <select id="wh_days" class="form-select border-0 bg-transparent text-white" style="max-width: 120px;">
                                <option value="Пн-Нд:">Пн-Нд</option>
                                <option value="Пн-Пт:">Пн-Пт</option>
                                <option value="Щодня:">Щодня</option>
                            </select>
                            <input type="time" id="wh_start" class="form-control border-0 bg-transparent text-white" value="09:00">
                            <span class="input-group-text border-0 bg-transparent text-white opacity-50">-</span>
                            <input type="time" id="wh_end" class="form-control border-0 bg-transparent text-white" value="20:00">
                            <button type="button" class="btn-glass border-0" onclick="generateWH()"><i class="fas fa-plus"></i></button>
                        </div>
                        <input name="working_hours" id="working_hours_input" class="glass-input" value="{biz.working_hours}" placeholder="Напр: Пн-Пт: 09:00-19:00">
                    </div>
                    <div class="mb-4">
                        <label class="form-label text-white">Системна інструкція (Prompt)</label>
                        <textarea name="prompt" class="glass-input" rows="12" style="font-family: 'Fira Code', monospace; font-size: 13px;">{biz.system_prompt if biz.system_prompt else ""}</textarea>
                    </div>
                    <div class="text-end"><button class="btn-primary-glow px-5 py-3"><i class="fas fa-save me-2"></i>Зберегти зміни</button></div>
                </form>
            </div>
        </div>
        
        <div class="tab-pane fade" id="pills-masters">
            <div class="row g-4"> 
                <div class="col-md-5">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4">Додати {l['master_single']}a</h6>
                        <form action="/admin/add-master" method="post">
                            <div class="mb-3"><input name="name" class="glass-input" placeholder="ПІБ" required></div>
                            <div class="mb-3">
                                <label class="form-label text-white">Роль / Посада</label>
                                <select name="emp_role" class="form-select">{roles_html}</select>
                            </div>
                            <div class="mb-3"><input name="working_hours" class="glass-input" placeholder="Графік (напр. Пн-Пт: 10:00-18:00)"></div>
                            <div class="mb-4">
                                <label class="form-label text-white">Навички / Послуги</label>
                                <div class="p-3 rounded-4" style="background: rgba(255,255,255,0.02); border: 0.5px solid var(--glass-border); max-height: 200px; overflow-y: auto;">
                                    {services_checkboxes}
                                </div>
                            </div>
                            <button class="btn-primary-glow w-100 py-3">Додати співробітника</button>
                        </form>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4">Список: {l['masters']}</h6>
                        <ul class="list-group list-group-flush bg-transparent">{masters_html}</ul>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="tab-pane fade" id="pills-services">
            <div class="row g-4"> 
                <div class="col-md-5">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4">Додати {l['service_single']}у</h6>
                        <form action="/admin/add-service" method="post">
                            <div class="mb-3"><input name="name" class="glass-input" placeholder="Назва" required></div>
                            <div class="row g-3 mb-4">
                                <div class="col-6"><label class="form-label text-white">Ціна (грн)</label><input name="price" type="number" step="0.01" class="glass-input" placeholder="0.00" required></div>
                                <div class="col-6"><label class="form-label text-white">Тривалість (хв)</label><input name="duration" type="number" class="glass-input" placeholder="60" required></div>
                            </div>
                            <button class="btn-primary-glow w-100 py-3">Додати послугу</button>
                        </form>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4">Прайс-лист</h6>
                        <ul class="list-group list-group-flush bg-transparent">{services_html}</ul>
                    </div>
                </div>
            </div>
        </div>

        <div class="tab-pane fade" id="pills-notifications">
            <div class="glass-card p-4 p-md-5" style="max-width: 800px;">
                <h5 class="fw-800 text-white mb-4">Сповіщення про нові записи</h5>
                <p class="small text-muted mb-4">Отримуйте миттєві сповіщення, коли клієнт записується через ШІ-асистента.</p>
                <form onsubmit="saveForm(event, '/admin/save-notification-settings')">
                    <div class="mb-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <label class="form-label m-0 text-white">Email для сповіщень</label>
                            <div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="email_enabled" {email_chk}></div>
                        </div>
                        <div id="email-inputs-container">{email_inputs_html}</div>
                        <button type="button" class="btn-glass py-2 px-4 mt-2" onclick="addEmailInput()"><i class="fas fa-plus me-2 text-primary"></i>Додати Email</button>
                    </div>
                    
                    <div class="p-4 rounded-4 mb-4" style="background: rgba(255,255,255,0.02); border: 0.5px solid var(--glass-border);">
                        <h6 class="fw-800 text-white mb-4"><i class="fas fa-envelope me-2 text-primary"></i>Налаштування SMTP (Пошта)</h6>
                        <div class="row g-3 mb-3">
                            <div class="col-md-8"><label class="form-label text-white">SMTP Сервер</label><input name="smtp_server" class="glass-input" value="{biz.smtp_server or ''}" placeholder="smtp.gmail.com"></div>
                            <div class="col-md-4"><label class="form-label text-white">Порт</label><input name="smtp_port" type="number" class="glass-input" value="{biz.smtp_port or 587}"></div>
                        </div>
                        <div class="row g-3 mb-3">
                            <div class="col-md-6"><label class="form-label text-white">Користувач</label><input name="smtp_user" class="glass-input" value="{biz.smtp_username or ''}" placeholder="Login / Email"></div>
                            <div class="col-md-6"><label class="form-label text-white">Пароль</label><input name="smtp_pass" type="password" class="glass-input" value="{biz.smtp_password or ''}" placeholder="••••••••"></div>
                        </div>
                        <div class="mb-0">
                            <label class="form-label text-white">Відправник (Sender Email)</label>
                            <input name="smtp_sender" class="glass-input" value="{biz.smtp_sender or ''}" placeholder="noreply@yourdomain.com">
                        </div>
                    </div>

                    <div class="mb-5">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <label class="form-label m-0 text-white">Telegram Chat ID для сповіщень</label>
                            <div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="tg_enabled" {tg_chk}></div>
                        </div>
                        <div id="tg-chat-id-inputs-container">{tg_chat_id_inputs_html}</div>
                        <button type="button" class="btn-glass py-2 px-4 mt-2" onclick="addTgInput()"><i class="fas fa-plus me-2 text-primary"></i>Додати Chat ID</button>
                    </div>
                    
                    <div class="text-end"><button class="btn-primary-glow px-5 py-3"><i class="fas fa-save me-2"></i>Зберегти налаштування</button></div>
                </form>
            </div>
        </div>
        
        {branches_tab_content}
        {api_tab_content}
        
        <div class="modal fade" id="createAccountModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
            <div class="modal-header"><h5 class="modal-title text-white">Акаунт співробітника</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
            <form action="/admin/create-master-account" method="post" class="d-flex flex-column h-100">
                <div class="modal-body overflow-y-auto">
                    <input type="hidden" name="id" id="accMasterId">
                    <p class="text-muted small mb-4">Створення доступу для: <strong id="accMasterName" class="text-white"></strong></p>
                    <div class="mb-3"><label class="form-label text-white">Логін (Телефон)</label><input name="login" class="glass-input" placeholder="+380..." required></div>
                    <div class="mb-0"><label class="form-label text-white">Пароль</label><input name="password" type="password" class="glass-input" placeholder="••••••••" required></div>
                </div>
                <div class="modal-footer">
                    <button class="btn-primary-glow w-100 py-3">Створити акаунт</button>
                </div>
            </form>
        </div></div></div>

        <div class="modal fade" id="apiKeyLogsModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered modal-lg mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
            <div class="modal-header"><h5 class="modal-title text-white">Історія запитів: <span id="logKeyName" class="text-primary"></span></h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
            <div class="modal-body overflow-y-auto">
                <div class="table-responsive">
                    <table class="glass-table">
                        <thead><tr><th>Час</th><th>Метод</th><th>Ендпоінт</th><th>IP</th><th>Статус</th></tr></thead>
                        <tbody id="apiKeyLogsTableBody">
                            <tr><td colspan="5" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Завантаження...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div></div></div>
    </div>"""
    scripts = """
    <script>
    function generateWH() { 
        const days = document.getElementById('wh_days').value;
        const start = document.getElementById('wh_start').value;
        const end = document.getElementById('wh_end').value;
        if(start && end) { 
            let input = document.getElementById('working_hours_input');
            let current = input.value.trim();
            let addition = `${days} ${start}-${end}`;
            if (current) { input.value = current + ', ' + addition; }
            else { input.value = addition; }
        }
    } 
    async function saveForm(event, url) {
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);
        const btn = form.querySelector('button[type="submit"], button:not([type])');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Збереження...';
        btn.disabled = true;

        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (data.ok) {
                showToast('Налаштування успішно збережено!');
            } else {
                showToast(data.msg || 'Сталася помилка', 'error');
            }
        } catch (e) {
            showToast('Помилка мережі', 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
    function addEmailInput() {
        const container = document.getElementById('email-inputs-container');
        const newDiv = document.createElement('div');
        newDiv.className = 'input-group mb-2';
        newDiv.innerHTML = `<input name="email" type="email" class="glass-input" style="border-radius: 12px 0 0 12px;" placeholder="example@email.com"><button class="btn btn-glass" style="border-radius: 0 12px 12px 0;" type="button" onclick="this.parentElement.remove()"><i class="fas fa-times text-danger"></i></button>`;
        container.appendChild(newDiv);
    }
    function addTgInput() {
        const container = document.getElementById('tg-chat-id-inputs-container');
        const newDiv = document.createElement('div');
        newDiv.className = 'input-group mb-2';
        newDiv.innerHTML = `<input name="tg_chat_id" class="glass-input" style="border-radius: 12px 0 0 12px;" placeholder="Наприклад: -100123456789"><button class="btn btn-glass" style="border-radius: 0 12px 12px 0;" type="button" onclick="this.parentElement.remove()"><i class="fas fa-times text-danger"></i></button>`;
        container.appendChild(newDiv);
    }
    function createMasterAccount(id, name) {
        document.getElementById('accMasterId').value = id;
        document.getElementById('accMasterName').innerText = name;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('createAccountModal')).show();
    }
    
    async function showApiKeyLogs(keyId, keyName) {
        document.getElementById('logKeyName').innerText = keyName;
        const tbody = document.getElementById('apiKeyLogsTableBody');
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Завантаження...</td></tr>';
        
        bootstrap.Modal.getOrCreateInstance(document.getElementById('apiKeyLogsModal')).show();
        
        try {
            const res = await fetch(`/admin/api/api-key-logs/${keyId}`);
            const logs = await res.json();
            
            if (logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">Історія запитів порожня</td></tr>';
                return;
            }
            
            tbody.innerHTML = logs.map(log => {
                let statusBadge = log.status_code >= 200 && log.status_code < 300 
                    ? `<span class="badge bg-success bg-opacity-10 text-success">${log.status_code}</span>`
                    : `<span class="badge bg-danger bg-opacity-10 text-danger">${log.status_code}</span>`;
                let methodColor = log.method === 'GET' ? 'text-info' : (log.method === 'POST' ? 'text-success' : (log.method === 'DELETE' ? 'text-danger' : 'text-warning'));
                return `<tr>
                    <td class="text-muted small">${log.time}</td>
                    <td class="fw-bold ${methodColor}">${log.method}</td>
                    <td><code class="text-white-50 bg-transparent p-0">${log.endpoint}</code></td>
                    <td class="text-muted small">${log.ip_address || '-'}</td>
                    <td>${statusBadge}</td>
                </tr>`;
            }).join('');
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-danger">Помилка завантаження історії</td></tr>';
        }
    }
    </script>
    """
    return get_layout(content, user, "set", scripts)

@router.get("/generator", response_class=HTMLResponse)
async def prompt_generator_page(user: User = Depends(get_current_user)):
    if not user or user.role not in ["owner", "admin", "manager"]: return RedirectResponse("/admin", status_code=303)
    
    content = """
    <div class="glass-card p-5">
        <div class="d-flex align-items-center mb-5">
            <div class="logo-icon me-4" style="width: 64px; height: 64px; background: rgba(52, 211, 153, 0.1); color: #34d399; font-size: 28px; border-radius: 20px; display: flex; align-items: center; justify-content: center;"><i class="fas fa-wand-magic-sparkles"></i></div>
            <div>
                <h4 class="fw-800 text-white mb-1" style="font-size: 28px; letter-spacing: -1px;">Конструктор Особистості ШІ</h4>
                <p class="text-muted small mb-0 fw-500">Налаштуйте поведінку асистента до дрібниць (30+ параметрів)</p>
            </div>
        </div>
        
        <form id="genForm" onsubmit="saveGeneratedPrompt(event)">
            <div class="row g-4"> 
                <div class="col-12"><h6 class="text-primary fw-800 mb-2" style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px;">🎭 Роль та Стиль</h6></div>
                <div class="col-md-3">
                    <label class="form-label text-white">Роль</label>
                    <select id="genRole" class="form-select">
                        <option value="Адміністратор">Адміністратор</option>
                        <option value="Турботливий помічник">Турботливий помічник</option>
                        <option value="Експерт-консультант">Експерт-консультант</option>
                        <option value="Sales-менеджер">Sales-менеджер (Активний)</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Тон</label>
                    <select id="genTone" class="form-select">
                        <option value="Діловий">Діловий</option>
                        <option value="Дружній">Дружній</option>
                        <option value="Елітний">Елітний/Преміум</option>
                        <option value="Грайливий">Грайливий</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Мова спілкування</label>
                    <select id="genLang" class="form-select">
                        <option value="Українська">Українська</option>
                        <option value="Англійська">Англійська</option>
                        <option value="Польська">Польська</option>
                        <option value="Мультимовний (підлаштовуватись)">Мультимовний</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Ім'я асистента</label>
                    <input id="genName" class="glass-input" placeholder="Напр. Аліна">
                </div>

                <div class="col-12 mt-5"><h6 class="text-primary fw-800 mb-2" style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px;">🧠 Поведінка та Реакції</h6></div>
                <div class="col-md-3">
                    <label class="form-label text-white">Емодзі</label>
                    <select id="genEmoji" class="form-select">
                        <option value="Помірно (1-2)">Помірно</option>
                        <option value="Багато (емоційно)">Багато</option>
                        <option value="Не використовувати">Без емодзі</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Довжина відповідей</label>
                    <select id="genLength" class="form-select">
                        <option value="Лаконічно (коротко)">Лаконічно</option>
                        <option value="Детально (розгорнуто)">Детально</option>
                        <option value="Середньо">Середньо</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Звернення</label>
                    <select id="genAddress" class="form-select">
                        <option value="На Ви">На Ви</option>
                        <option value="На Ти">На Ти</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Реакція на невідоме</label>
                    <select id="genUnknown" class="form-select">
                        <option value="Кликати адміна">Кликати адміна</option>
                        <option value="Просити уточнити">Просити уточнити</option>
                        <option value="Імпровізувати">М'яко обходити</option>
                    </select>
                </div>

                <div class="col-md-3">
                    <label class="form-label text-white">Формальність</label>
                    <select id="genFormality" class="form-select">
                        <option value="Офіційно">Офіційно</option>
                        <option value="Нейтрально">Нейтрально</option>
                        <option value="Неформально">Неформально</option>
                        <option value="Преміум (дуже ввічливо)">Преміум</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Реакція на негатив</label>
                    <select id="genNegative" class="form-select">
                        <option value="Заспокоїти">Заспокоїти</option>
                        <option value="Вибачитись">Вибачитись</option>
                        <option value="Перевести на адміна">Перевести на адміна</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Реакція на "дякую"</label>
                    <select id="genThanks" class="form-select">
                        <option value="Коротко">Коротко</option>
                        <option value="Розгорнуто">Розгорнуто</option>
                        <option value="Не відповідати">Не відповідати</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Реакція на "привіт"</label>
                    <select id="genHello" class="form-select">
                        <option value="Відповісти">Відповісти</option>
                        <option value="Ігнорувати">Ігнорувати</option>
                    </select>
                </div>

                <div class="col-12 mt-5"><h6 class="text-primary fw-800 mb-2" style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px;">📈 Стратегія продажів та бронювання</h6></div>
                <div class="col-md-3">
                    <label class="form-label text-white">Допродаж (Upsell)</label>
                    <select id="genUpsell" class="form-select">
                        <option value="Проактивно пропонувати додаткові послуги">Проактивно пропонувати</option>
                        <option value="Пропонувати тільки після успішного запису">Пропонувати після запису</option>
                        <option value="Ніколи не пропонувати">Не пропонувати</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Підтвердження запису</label>
                    <select id="genBookingConfirm" class="form-select">
                        <option value="Завжди питати фінальне підтвердження">Завжди питати підтвердження</option>
                        <option value="Бронювати одразу, якщо є всі дані">Бронювати одразу</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Робота зі знижками</label>
                    <select id="genDiscounts" class="form-select">
                        <option value="Завжди згадувати про персональну знижку клієнта">Завжди згадувати</option>
                        <option value="Згадувати тільки за прямим запитом">Згадувати за запитом</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Пропозиція часу</label>
                    <select id="genTimeSuggest" class="form-select">
                        <option value="Пропонувати 3-4 конкретних вільних слоти">Пропонувати конкретні слоти</option>
                        <option value="Питати у клієнта бажаний час, а потім перевіряти">Питати бажаний час</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Завершення діалогу</label>
                    <select id="genEnding" class="form-select">
                        <option value="Завжди питати 'Чим ще можу допомогти?'">Завжди питати 'Чим ще?'</option>
                        <option value="Ввічливо прощатися після вирішення питання">Ввічливо прощатися</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Збір контактів</label>
                    <select id="genContacts" class="form-select">
                        <option value="Питати ім'я/телефон на початку діалогу">Питати на початку</option>
                        <option value="Питати ім'я/телефон тільки при бронюванні">Питати при бронюванні</option>
                    </select>
                </div>

                <div class="col-12 mt-5"><h6 class="text-primary fw-800 mb-2" style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px;">⚙️ Розширена логіка та знання</h6></div>
                <div class="col-md-3">
                    <label class="form-label text-white">Джерело знань</label>
                    <select id="genKnowledge" class="form-select">
                        <option value="Тільки надана інформація (прайс, графік)">Тільки надана інформація</option>
                        <option value="Можна використовувати загальні знання для підтримки розмови">Дозволити загальні знання</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Професійний жаргон</label>
                    <select id="genJargon" class="form-select">
                        <option value="Використовувати професійні терміни, якщо доречно">Використовувати</option>
                        <option value="Уникати складних термінів, говорити простою мовою">Уникати</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Реакція на компліменти</label>
                    <select id="genCompliment" class="form-select">
                        <option value="Скромно дякувати ('Дякую, дуже приємно!')">Скромно дякувати</option>
                        <option value="Впевнено ('Дякую, я стараюся!')">Впевнено</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Стратегія уточнення</label>
                    <select id="genClarify" class="form-select">
                        <option value="Перефразувати питання, щоб переконатись у розумінні">Перефразувати питання</option>
                        <option value="Просити надати більше деталей">Просити більше деталей</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Подальші питання</label>
                    <select id="genFollowup" class="form-select">
                        <option value="Ставити уточнюючі питання для кращого сервісу">Ставити уточнюючі питання</option>
                        <option value="Не ставити зайвих питань">Не ставити зайвих питань</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label text-white">Показ цін</label>
                    <select id="genPrices" class="form-select">
                        <option value="Завжди вказувати ціну послуги при обговоренні">Завжди вказувати ціну</option>
                        <option value="Вказувати ціну тільки за прямим запитом клієнта">Тільки за запитом</option>
                    </select>
                </div>

                <div class="col-12 mt-5 text-end">
                    <button type="submit" class="btn-primary-glow px-5 py-3"><i class="fas fa-save me-2"></i>Зберегти згенерований Prompt</button>
                </div>
            </div>
        </form>
        <div class="section-divider my-5"></div>
        <div class="glass-card p-4">
            <h5 class="fw-800 text-white mb-4">Згенерований Prompt</h5>
            <textarea id="generatedPrompt" class="glass-input" rows="15" style="font-family: 'Fira Code', monospace; font-size: 13px;" readonly></textarea>
        </div>
    </div>
    """
    scripts = """
    <script>
    function generatePrompt() {
        const role = document.getElementById('genRole').value;
        const tone = document.getElementById('genTone').value;
        const lang = document.getElementById('genLang').value;
        const name = document.getElementById('genName').value;
        const emoji = document.getElementById('genEmoji').value;
        const length = document.getElementById('genLength').value;
        const address = document.getElementById('genAddress').value;
        const unknown = document.getElementById('genUnknown').value;
        const formality = document.getElementById('genFormality').value;
        const negative = document.getElementById('genNegative').value;
        const thanks = document.getElementById('genThanks').value;
        const hello = document.getElementById('genHello').value;
        const upsell = document.getElementById('genUpsell').value;
        const bookingConfirm = document.getElementById('genBookingConfirm').value;
        const discounts = document.getElementById('genDiscounts').value;
        const timeSuggest = document.getElementById('genTimeSuggest').value;
        const ending = document.getElementById('genEnding').value;
        const contacts = document.getElementById('genContacts').value;
        const knowledge = document.getElementById('genKnowledge').value;

        let prompt = `Ти - ${role} нашого бізнесу. Твоє ім'я ${name || 'AI Асистент'}.`;
        prompt += `\\nТвій стиль спілкування: ${tone}, ${formality}.`;
        prompt += `\\nМова спілкування: ${lang}.`;
        prompt += `\\nВикористовуй емодзі: ${emoji}.`;
        prompt += `\\nДовжина відповідей: ${length}.`;
        prompt += `\\nЗвертайся до клієнтів: ${address}.`;
        prompt += `\\nЯкщо клієнт запитує щось невідоме: ${unknown}.`;
        prompt += `\\nРеакція на негатив: ${negative}.`;
        prompt += `\\nРеакція на "дякую": ${thanks}.`;
        prompt += `\\nРеакція на "привіт": ${hello}.`;
        prompt += `\\nСтратегія допродажу: ${upsell}.`;
        prompt += `\\nПідтвердження бронювання: ${bookingConfirm}.`;
        prompt += `\\nРобота зі знижками: ${discounts}.`;
        prompt += `\\nПропозиція часу: ${timeSuggest}.`;
        prompt += `\\n\\nТвоя головна задача - допомагати клієнтам з питаннями про послуги, ціни, запис та графік роботи.`;

        document.getElementById('generatedPrompt').value = prompt;
    }

    async function saveGeneratedPrompt(event) {
        event.preventDefault();
        const promptText = document.getElementById('generatedPrompt').value;
        if (!promptText) {
            showToast('Згенеруйте Prompt спочатку!', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('prompt', promptText);

        const btn = event.target.querySelector('button[type="submit"]');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Збереження...';
        btn.disabled = true;

        try {
            const response = await fetch('/admin/save-prompt', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (data.success) {
                showToast('Prompt успішно збережено!');
            } else {
                showToast(data.error || 'Помилка збереження Prompt', 'error');
            }
        } catch (e) {
            showToast('Помилка мережі', 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }

    document.addEventListener('DOMContentLoaded', generatePrompt);
    document.getElementById('genRole').addEventListener('change', generatePrompt);
    document.getElementById('genTone').addEventListener('change', generatePrompt);
    document.getElementById('genLang').addEventListener('change', generatePrompt);
    document.getElementById('genName').addEventListener('input', generatePrompt);
    document.getElementById('genEmoji').addEventListener('change', generatePrompt);
    document.getElementById('genLength').addEventListener('change', generatePrompt);
    document.getElementById('genAddress').addEventListener('change', generatePrompt);
    document.getElementById('genUnknown').addEventListener('change', generatePrompt);
    document.getElementById('genFormality').addEventListener('change', generatePrompt);
    document.getElementById('genNegative').addEventListener('change', generatePrompt);
    document.getElementById('genThanks').addEventListener('change', generatePrompt);
    document.getElementById('genHello').addEventListener('change', generatePrompt);
    document.getElementById('genUpsell').addEventListener('change', generatePrompt);
    document.getElementById('genBookingConfirm').addEventListener('change', generatePrompt);
    document.getElementById('genDiscounts').addEventListener('change', generatePrompt);
    document.getElementById('genTimeSuggest').addEventListener('change', generatePrompt);
    document.getElementById('genEnding').addEventListener('change', generatePrompt);
    document.getElementById('genContacts').addEventListener('change', generatePrompt);
    </script>
    """
    return get_layout(content, user, "gen", scripts)


@router.post("/save-prompt")
async def save_prompt(
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    temp: Optional[float] = Form(None),
    tokens: Optional[int] = Form(None),
    working_hours: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "admin", "manager"]:
        return {"success": False, "ok": False, "error": "Unauthorized", "msg": "Помилка авторизації"}

    biz = await db.get(Business, user.business_id)
    if biz:
        biz.system_prompt = prompt
        if model is not None:
            biz.ai_model = model
        if temp is not None:
            biz.ai_temperature = temp
        if tokens is not None:
            biz.ai_max_tokens = tokens
        if working_hours is not None:
            biz.working_hours = working_hours
        await db.commit()
        await log_action(db, user.business_id, user.id, "Оновлено Prompt", "Системний Prompt AI асистента оновлено.")
        return {"success": True, "ok": True, "message": "Prompt успішно збережено!", "msg": "Prompt успішно збережено!"}
    return {"success": False, "ok": False, "error": "Business not found", "msg": "Бізнес не знайдено"}


@router.post("/add-master")
async def add_master(
    name: str = Form(...),
    emp_role: str = Form(...),
    working_hours: Optional[str] = Form(None),
    services: List[int] = Form([]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "superadmin", "admin", "manager"]:
        return RedirectResponse("/", status_code=303)

    new_master = Master(business_id=user.business_id, name=name, role=emp_role, working_hours=working_hours)
    db.add(new_master)
    await db.flush()
    await db.refresh(new_master)

    for service_id in services:
        master_service = MasterService(master_id=new_master.id, service_id=service_id)
        db.add(master_service)

    await db.commit()
    await log_action(db, user.business_id, user.id, "Додано співробітника", f"Додано співробітника '{name}' з роллю '{emp_role}'.")

    return RedirectResponse("/admin/settings?msg=added", status_code=303)


@router.post("/delete-master")
async def delete_master(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "superadmin", "admin", "manager"]:
        return RedirectResponse("/", status_code=303)

    master_to_delete = await db.get(Master, id)
    if master_to_delete and master_to_delete.business_id == user.business_id:
        await db.execute(delete(MasterService).where(MasterService.master_id == id))
        await db.delete(master_to_delete)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено співробітника", f"Видалено співробітника '{master_to_delete.name}'.")

    return RedirectResponse("/admin/settings?msg=deleted", status_code=303)


@router.post("/add-service")
async def add_service(
    name: str = Form(...),
    price: float = Form(...),
    duration: int = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "superadmin", "admin"]:
        return RedirectResponse("/", status_code=303)

    new_service = Service(business_id=user.business_id, name=name, price=price, duration=duration)
    db.add(new_service)
    await db.commit()
    await log_action(db, user.business_id, user.id, "Додано послугу", f"Додано послугу '{name}' ({price} грн, {duration} хв).")

    return RedirectResponse("/admin/settings?msg=added", status_code=303)


@router.post("/delete-service")
async def delete_service(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "superadmin", "admin"]:
        return RedirectResponse("/", status_code=303)

    service_to_delete = await db.get(Service, id)
    if service_to_delete and service_to_delete.business_id == user.business_id:
        await db.execute(delete(MasterService).where(MasterService.service_id == id))
        await db.delete(service_to_delete)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено послугу", f"Видалено послугу '{service_to_delete.name}'.")

    return RedirectResponse("/admin/settings?msg=deleted", status_code=303)


@router.post("/create-master-account")
async def create_master_account(
    id: int = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "superadmin", "admin"]:
        return RedirectResponse("/", status_code=303)

    master = await db.get(Master, id)
    if master and master.business_id == user.business_id:
        existing_user = await db.scalar(select(User).where(User.username == login))
        if existing_user:
            return RedirectResponse("/admin/settings?msg=login_exists", status_code=303)

        new_user = User(username=login, password=await run_in_threadpool(hash_password, password), role="master", business_id=user.business_id, master_id=master.id)
        db.add(new_user)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Створено акаунт співробітника", f"Створено акаунт для '{master.name}' з логіном '{login}'.")

    return RedirectResponse("/admin/settings?msg=added", status_code=303)


@router.post("/add-branch")
async def add_branch(
    name: str = Form(...),
    city: str = Form(...),
    address: str = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "owner":
        return RedirectResponse("/", status_code=303)

    existing_user = await db.scalar(select(User).where(User.username == login))
    if existing_user:
        return RedirectResponse("/admin/settings?msg=login_exists", status_code=303)

    new_branch = Business(
        name=name, 
        city=city, 
        address=address, 
        parent_id=user.business_id, 
        type=user.business.type, 
        plan_type=user.business.plan_type,
        has_ai_bot=True,
        integration_enabled=True
    )
    db.add(new_branch)
    await db.flush()
    await db.refresh(new_branch)

    new_user = User(username=login, password=hash_password(password), role="admin", business_id=new_branch.id)
    db.add(new_user)
    await db.commit()
    await log_action(db, user.business_id, user.id, "Створено філію", f"Створено філію '{name}' з логіном '{login}'.")

    return RedirectResponse("/admin/settings?msg=branch_added", status_code=303)


@router.post("/delete-branch")
async def delete_branch(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner":
        return RedirectResponse("/", status_code=303)

    branch_to_delete = await db.get(Business, id)
    if branch_to_delete and branch_to_delete.parent_id == user.business_id:
        masters_subq = select(Master.id).where(Master.business_id == id)
        await db.execute(delete(MasterService).where(MasterService.master_id.in_(masters_subq)))
        
        appts_subq = select(Appointment.id).where(Appointment.business_id == id)
        await db.execute(delete(AppointmentConfirmation).where(AppointmentConfirmation.appointment_id.in_(appts_subq)))

        await db.execute(delete(NPSReview).where(NPSReview.business_id == id))
        await db.execute(delete(CustomerSegment).where(CustomerSegment.business_id == id))
        await db.execute(delete(User).where(User.business_id == id))
        await db.execute(delete(Appointment).where(Appointment.business_id == id))
        await db.execute(delete(Customer).where(Customer.business_id == id))
        await db.execute(delete(Master).where(Master.business_id == id))
        await db.execute(delete(Service).where(Service.business_id == id))
        await db.execute(delete(Product).where(Product.business_id == id))
        await db.execute(delete(MonthlyPaymentLog).where(MonthlyPaymentLog.business_id == id))
        await db.execute(delete(ActionLog).where(ActionLog.business_id == id))
        await db.execute(delete(ChatLog).where(ChatLog.business_id == id))
        
        await db.delete(branch_to_delete)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено філію", f"Видалено філію '{branch_to_delete.name}'.")

    return RedirectResponse("/admin/settings?msg=branch_deleted", status_code=303)


@router.get("/switch-to-branch/{branch_id}")
async def switch_to_branch(branch_id: int, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner":
        return RedirectResponse("/", status_code=303)

    branch = await db.get(Business, branch_id)
    if branch and branch.parent_id == user.business_id:
        branch_owner = await db.scalar(select(User).where(User.business_id == branch_id).where(User.role == 'owner'))
        if branch_owner:
            request.session["user_id"] = branch_owner.id
            return RedirectResponse("/admin", status_code=303)

    return RedirectResponse("/admin/settings", status_code=303)


@router.post("/save-notification-settings")
async def save_notification_settings(
    email: List[str] = Form([]),
    email_enabled: bool = Form(False),
    smtp_server: Optional[str] = Form(None),
    smtp_port: Optional[int] = Form(None),
    smtp_user: Optional[str] = Form(None),
    smtp_pass: Optional[str] = Form(None),
    smtp_sender: Optional[str] = Form(None),
    tg_chat_id: List[str] = Form([]),
    tg_enabled: bool = Form(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "admin"]:
        return {"ok": False, "msg": "Unauthorized"}

    biz = await db.get(Business, user.business_id)
    if biz:
        biz.email_notifications_enabled = email_enabled
        biz.notification_email = ",".join([e for e in email if e])
        biz.smtp_server = smtp_server
        biz.smtp_port = smtp_port
        biz.smtp_username = smtp_user
        biz.smtp_password = smtp_pass
        biz.smtp_sender = smtp_sender

        biz.telegram_notifications_enabled = tg_enabled
        biz.telegram_notification_chat_id = ",".join([cid for cid in tg_chat_id if cid])
        
        await db.commit()
        await log_action(db, user.business_id, user.id, "Оновлено налаштування сповіщень", "Налаштування сповіщень оновлено.")
        return {"ok": True, "msg": "Налаштування сповіщень збережено!"}
    return {"ok": False, "msg": "Business not found"}


@router.post("/update-master-profile")
async def update_master_profile(
    bot_token: Optional[str] = Form(None),
    new_password: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "master":
        return RedirectResponse("/", status_code=303)

    master = await db.get(Master, user.master_id)
    if master:
        master.personal_bot_token = bot_token
        if new_password:
            user.password = hash_password(new_password)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Оновлено профіль майстра", f"Профіль майстра '{master.name}' оновлено.")

    return RedirectResponse("/admin/settings?msg=saved", status_code=303)

@router.post("/create-api-key")
async def create_first_api_key(name: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin"]:
        return RedirectResponse("/", status_code=303)

    new_api_key_value = generate_api_key()
    
    new_api_key = ApiKey(
        business_id=user.business_id,
        api_key=new_api_key_value, # Store the key directly
        name=name,
        is_active=True,
        created_at=datetime.now()
    )
    db.add(new_api_key)
    await db.commit()
    
    return RedirectResponse("/admin/settings?msg=API+ключ+створено!+Скопіюйте+його+з+поля+вище.", status_code=303)


@router.post("/toggle-api-key")
async def toggle_api_key(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin"]:
        return RedirectResponse("/", status_code=303)

    api_key = await db.get(ApiKey, id)
    if api_key and api_key.business_id == user.business_id:
        # Перемикаємо статус (з активного на вимкнений і навпаки)
        api_key.is_active = not api_key.is_active
        await db.commit()
        state = "увімкнено" if api_key.is_active else "вимкнено"
        await log_action(db, user.business_id, user.id, "Зміна статусу API ключа", f"API ключ '{api_key.name}' {state}.")

    return RedirectResponse("/admin/settings?msg=saved", status_code=303)


@router.post("/delete-api-key")
async def delete_api_key(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin"]:
        return RedirectResponse("/", status_code=303)

    api_key = await db.get(ApiKey, id)
    if api_key and api_key.business_id == user.business_id:
        key_name = api_key.name
        await db.delete(api_key)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено API ключ", f"API ключ '{key_name}' видалено остаточно.")

    return RedirectResponse("/admin/settings?msg=deleted", status_code=303)

@router.get("/api/api-key-logs/{key_id}")
async def get_api_key_logs(key_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "master"]:
        return []
        
    api_key = await db.get(ApiKey, key_id)
    if not api_key or api_key.business_id != user.business_id:
        return []
        
    logs = (await db.execute(
        select(ApiRequestLog)
        .where(ApiRequestLog.api_key_id == key_id)
        .order_by(desc(ApiRequestLog.created_at))
        .limit(100)
    )).scalars().all()
    
    return [{
        "endpoint": html.escape(l.endpoint),
        "method": html.escape(l.method),
        "status_code": l.status_code,
        "ip_address": html.escape(l.ip_address) if l.ip_address else "-",
        "time": l.created_at.strftime('%d.%m.%Y %H:%M:%S')
    } for l in logs]


@router.get("/klienci", response_class=HTMLResponse)
async def clients_page(q: str = Query("", max_length=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager", "master"]: return RedirectResponse("/", status_code=303)
    customers = (await db.execute(select(Customer).where(Customer.business_id == user.business_id).order_by(desc(Customer.id)))).scalars().all()
    
    query = q.strip().casefold()
    if query:
        customers = [customer for customer in customers if query in (customer.name or "").casefold()
                     or query in customer.phone_number.casefold()]

    biz_type = user.business.type if user.business else "barbershop"
    if biz_type == 'school':
        l = {"clients": "Учні"}
    else:
        l = LABELS.get(biz_type, LABELS.get("generic", {"clients": "Клієнти"}))
        
    rows = ""
    for c in customers:
        badge = "<span class='badge bg-danger bg-opacity-10 text-danger'>Заблоковано</span>" if getattr(c, 'is_blocked', False) else "<span class='badge bg-success bg-opacity-10 text-success'>Активний</span>"
        btn_icon = "fa-unlock text-success" if getattr(c, 'is_blocked', False) else "fa-ban text-danger"
        btn_title = "Розблокувати клієнта" if getattr(c, 'is_blocked', False) else "Заблокувати клієнта (Чорний список)"
        btn_edit = f"<button type='button' class='btn btn-glass btn-sm me-1' data-customer-edit=\"{html.escape(json.dumps([c.id, c.name or '', c.phone_number or '', c.discount_percent, c.notes or '']), quote=True)}\" title='Редагувати профіль'><i class='fas fa-edit text-info'></i></button>"
        
        rows += f"""
        <tr>
            <td><span class="text-muted">#{c.id}</span></td>
            <td class="fw-bold">{html.escape(c.name or 'Гість')}</td>
            <td>{html.escape(c.phone_number)}</td>
            <td><span class="badge bg-primary bg-opacity-10 text-primary">{c.discount_percent}%</span></td>
            <td>{badge}</td>
            <td><span class="small text-muted">{html.escape(c.notes or '-')}</span></td>
            <td class="text-end">
                {btn_edit}
                <form action='/admin/toggle-client-block' method='post' style='display:inline' onsubmit="return confirm('Ви впевнені?');">
                    <input type='hidden' name='id' value='{c.id}'>
                    <button type='submit' class='btn btn-glass btn-sm' title='{btn_title}'><i class="fas {btn_icon}"></i></button>
                </form>
            </td>
        </tr>"""
        
    no_customers = "За цим запитом клієнтів не знайдено" if query else "Клієнтів ще немає"
    empty_row = f'<tr><td colspan="7" class="text-center py-5 text-muted">{no_customers}</td></tr>'
    content = f"""
    <div class="glass-card p-4">
        <div class="d-flex align-items-center gap-3 mb-4">
            <div class="d-flex align-items-center justify-content-center flex-shrink-0" style="width: 46px; height: 46px; border-radius: 14px; background: linear-gradient(135deg, rgba(187,134,252,0.22), rgba(96,165,250,0.14)); border: 1px solid rgba(187,134,252,0.22); color: #d9c7ff;">
                <i class="fas fa-users"></i>
            </div>
            <div class="min-w-0">
                <h5 class="fw-800 text-white mb-1">{l.get('clients', 'Клієнти')}</h5>
                <div class="small text-white-50">Єдина база контактів, знижок, статусів і нотаток</div>
            </div>
        </div>
        <form class="d-flex flex-wrap align-items-end gap-2 mb-3" action="/admin/klienci" method="get">
            <div><label for="client-query" class="form-label">Пошук за ім’ям або номером</label>
            <input id="client-query" name="q" type="search" class="form-control" maxlength="100" value="{html.escape(q, quote=True)}"></div>
            <button class="btn-glass px-3 py-2">Знайти</button>
            <a class="btn-glass px-3 py-2" href="/admin/klienci">Скинути</a>
        </form>
        <div class="table-responsive w-full overflow-x-auto whitespace-nowrap block">
            <table class="glass-table">
                <thead><tr><th>ID</th><th>Ім'я</th><th>Телефон</th><th>Знижка</th><th>Статус</th><th>Нотатки</th><th class="text-end">Дії</th></tr></thead>
                <tbody>{rows or empty_row}</tbody>
            </table>
        </div>
    </div>
    <div class="modal fade" id="editCustomerModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title text-white">Редагування клієнта</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/admin/update-customer" method="post" class="d-flex flex-column h-100">
            <div class="modal-body overflow-y-auto">
                <input type="hidden" name="id" id="editCustId">
                <div class="mb-3"><label class="form-label text-white">Ім'я</label><input name="name" id="editCustName" class="glass-input" required></div>
                <div class="mb-3"><label class="form-label text-white">Телефон</label><input name="phone" id="editCustPhone" class="glass-input" required></div>
                <div class="mb-3"><label class="form-label text-white">Знижка (%)</label><input name="discount_percent" type="number" step="0.1" id="editCustDiscount" class="glass-input"></div>
                <div class="mb-0"><label class="form-label text-white">Нотатки</label><textarea name="notes" id="editCustNotes" class="glass-input" rows="3"></textarea></div>
            </div>
            <div class="modal-footer"><button type="submit" class="btn-primary-glow w-100 py-3">Зберегти зміни</button></div>
        </form>
    </div></div></div>
    """
    scripts = """
    <script>
    function editCustomer(id, name, phone, discount, notes) {
        document.getElementById('editCustId').value = id;
        document.getElementById('editCustName').value = name;
        document.getElementById('editCustPhone').value = phone;
        document.getElementById('editCustDiscount').value = discount;
        document.getElementById('editCustNotes').value = notes;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('editCustomerModal')).show();
    }
    </script>
    """
    return get_layout(content, user, "kli", scripts=scripts)


@router.post("/toggle-client-block")
async def toggle_client_block(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager", "master"]: 
        return RedirectResponse("/", status_code=303)
    
    customer = await db.get(Customer, id)
    if customer and customer.business_id == user.business_id:
        customer.is_blocked = not getattr(customer, 'is_blocked', False)
        await db.commit()
        status_text = "заблоковано" if customer.is_blocked else "розблоковано"
        await log_action(db, user.business_id, user.id, "Статус клієнта", f"Клієнта '{customer.name or customer.phone_number}' {status_text}.")
    return RedirectResponse("/admin/klienci?msg=saved", status_code=303)


@router.post("/update-customer")
async def update_customer(
    id: int = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    discount_percent: float = Form(0.0),
    notes: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "admin", "manager", "master"]: 
        return RedirectResponse("/", status_code=303)
    
    customer = await db.get(Customer, id)
    if customer and customer.business_id == user.business_id:
        customer.name = name
        customer.phone_number = phone
        customer.discount_percent = discount_percent
        customer.notes = notes
        await db.commit()
        await log_action(db, user.business_id, user.id, "Оновлено клієнта", f"Профіль клієнта '{name}' оновлено.")
    return RedirectResponse("/admin/klienci?msg=saved", status_code=303)


@router.get("/finance", response_class=HTMLResponse)
async def finance_page(error: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager"]: return RedirectResponse("/", status_code=303)
    is_demo = getattr(user, "is_demo_workspace", False)
    products = (await db.execute(select(Product).where(Product.business_id == user.business_id).order_by(desc(Product.id)))).scalars().all()
    error_message = {
        "image": "Завантажте фото PNG, JPEG або WebP до 5 МБ.",
        "fields": "Перевірте назву, ціну та залишок товару.",
    }.get(error)
    photo_field = "" if is_demo else """
        <div class="mb-4">
            <label for="product-photo" class="form-label">Фото товару</label>
            <input id="product-photo" type="file" name="image" class="form-control" accept="image/*">
        </div>
    """
    
    rows = ""
    for p in products:
        variants_html = ""
        if p.variants:
            try:
                variants = json.loads(p.variants)
                variants_html = "<ul class='list-unstyled mb-0 small text-muted'>"
                for v in variants:
                    variants_html += f"<li>{html.escape(str(v.get('color', '')))} {html.escape(str(v.get('size', '')))}: {html.escape(str(v.get('stock', 0)))} шт.</li>"
                variants_html += "</ul>"
            except:
                variants_html = "<span class='small text-danger'>Помилка варіантів</span>"

        img_tag = f"<img src='{p.image_url}' style='width: 48px; height: 48px; object-fit: cover; border-radius: 12px; border: 1px solid var(--glass-border);'>" if getattr(p, 'image_url', None) else "<div style='width: 48px; height: 48px; border-radius: 12px; background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border); display: flex; align-items: center; justify-content: center;'><i class='fas fa-image text-white-50'></i></div>"

        rows += f"""
        <tr>
            <td>{img_tag}</td>
            <td><span class="text-muted">{html.escape(p.sku or '-')}</span></td>
            <td class="fw-bold">{html.escape(p.name)}</td>
            <td>{variants_html}</td>
            <td>{p.stock} шт.</td>
            <td class="text-success fw-bold">{p.unit_cost} грн</td>
            <td class="text-end">
                 <form action='/admin/delete-product' method='post' style='display:inline' onsubmit="return confirm('Видалити товар?');">
                    <input type='hidden' name='id' value='{p.id}'>
                    <button class='btn btn-glass btn-sm'><i class="fas fa-trash text-danger"></i></button>
                </form>
            </td>
        </tr>"""
        
    content = f"""
    <div class="row g-4">
        <div class="col-lg-5">
            <div class="glass-card p-4">
                <h5 class="fw-800 text-white mb-4"><i class="fas fa-plus-circle text-primary me-2"></i>Додати новий товар</h5>
                {f'<p class="alert alert-danger" role="alert">{error_message}</p>' if error_message else ""}
                <form action="/admin/add-product" method="post" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label class="form-label">Назва товару</label>
                        <input name="name" class="glass-input" placeholder="Напр. Шампунь 'Сила Вовка'" required>
                    </div>
                    <div class="row g-3 mb-3">
                        <div class="col-6">
                            <label class="form-label">Артикул (SKU)</label>
                            <input name="sku" class="glass-input" placeholder="SH-001">
                        </div>
                        <div class="col-6">
                            <label class="form-label">Ціна продажу (грн)</label>
                            <input name="unit_cost" type="number" min="0" step="0.01" class="glass-input" placeholder="0.00" required>
                        </div>
                    </div>
                    
                    {photo_field}
                    
                    <div class="p-3 rounded-4" style="background: rgba(255,255,255,0.02); border: 0.5px solid var(--glass-border);">
                        <h6 class="fw-800 text-white mb-3">Варіанти товару (колір, розмір, кількість)</h6>
                        <div id="variants-container">
                            <!-- JS will add variant rows here -->
                        </div>
                        <button type="button" class="btn-glass py-2 px-3 mt-2" onclick="addVariantRow()">
                            <i class="fas fa-plus me-2 text-primary"></i>Додати варіант
                        </button>
                    </div>

                    <button type="submit" class="btn-primary-glow w-100 py-3 mt-4">Додати товар на склад</button>
                </form>
            </div>
        </div>
        <div class="col-lg-7">
            <div class="glass-card p-4">
                <h5 class="fw-800 text-white mb-4"><i class="fas fa-boxes-stacked text-success me-2"></i>Склад та Товари</h5>
                <div class="table-responsive w-full overflow-x-auto whitespace-nowrap block">
                    <table class="glass-table">
                        <thead><tr><th>Фото</th><th>Артикул</th><th>Назва</th><th>Варіанти</th><th>Загалом</th><th>Ціна</th><th class="text-end">Дії</th></tr></thead>
                        <tbody>{rows if rows else '<tr><td colspan="7" class="text-center py-5 text-muted">Товарів ще немає</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    """
    scripts = """
    <script>
    function addVariantRow() {
        const container = document.getElementById('variants-container');
        const newRow = document.createElement('div');
        newRow.className = 'row g-2 mb-2 align-items-center';
        newRow.innerHTML = `
            <div class="col-4"><input name="variant_color" class="glass-input" placeholder="Колір"></div>
            <div class="col-4"><input name="variant_size" class="glass-input" placeholder="Розмір/Об'єм"></div>
            <div class="col-3"><input name="variant_stock" type="number" min="0" max="1000000" class="glass-input" placeholder="К-сть" value="1"></div>
            <div class="col-1 text-end"><button type="button" class="btn btn-glass btn-sm" onclick="this.parentElement.parentElement.remove()"><i class="fas fa-times text-danger"></i></button></div>
        `;
        container.appendChild(newRow);
    }
    document.addEventListener('DOMContentLoaded', addVariantRow); // Add one row by default
    </script>
    """
    return get_layout(content, user, "fin", scripts)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin"]: return RedirectResponse("/", status_code=303)
    logs = (await db.execute(select(ActionLog).where(ActionLog.business_id == user.business_id).order_by(desc(ActionLog.created_at)).limit(100))).scalars().all()
    
    rows = ""
    for l in logs:
        rows += f"""
        <tr>
            <td class="text-muted small">{l.created_at.strftime('%d.%m.%Y %H:%M')}</td>
            <td><span class="badge bg-info bg-opacity-10 text-info">{html.escape(l.action)}</span></td>
            <td><span class="text-white-50">{html.escape(l.details)}</span></td>
        </tr>"""
        
    content = f"""
    <div class="glass-card p-4">
        <h5 class="fw-800 text-white mb-4"><i class="fas fa-clock-rotate-left text-warning me-2"></i>Журнал подій</h5>
        <div class="table-responsive w-full overflow-x-auto whitespace-nowrap block">
            <table class="glass-table">
                <thead><tr><th>Дата та час</th><th>Дія</th><th>Деталі</th></tr></thead>
                <tbody>{rows if rows else '<tr><td colspan="3" class="text-center py-5 text-muted">Подій ще немає</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return get_layout(content, user, "logs")

@router.post("/add-product")
async def add_product(
    name: str = Form(...),
    sku: Optional[str] = Form(None),
    unit_cost: float = Form(...),
    variant_color: List[str] = Form([]),
    variant_size: List[str] = Form([]),
    variant_stock: List[str] = Form([]),
    image: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "admin", "manager"]:
        return RedirectResponse("/", status_code=303)

    name = name.strip()
    if not name or not math.isfinite(unit_cost) or unit_cost < 0:
        return RedirectResponse("/admin/finance?error=fields", status_code=303)
    if getattr(user, "is_demo_workspace", False) and image and image.filename:
        return RedirectResponse("/admin/finance?error=fields", status_code=303)

    variants = []
    total_stock = 0
    for i in range(len(variant_color)):
        try:
            stock = int(variant_stock[i])
            if not 0 <= stock <= 1_000_000:
                return RedirectResponse("/admin/finance?error=fields", status_code=303)
            variants.append({
                "color": variant_color[i],
                "size": variant_size[i],
                "stock": stock
            })
            total_stock += stock
        except (ValueError, IndexError):
            continue
    
    image_url = None
    if image and image.filename:
        content = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return RedirectResponse("/admin/finance?error=image", status_code=303)
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = ".png"
        elif content.startswith(b"\xff\xd8\xff"):
            extension = ".jpg"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            extension = ".webp"
        else:
            return RedirectResponse("/admin/finance?error=image", status_code=303)
        filename = f"{secrets.token_hex(16)}{extension}"
        folder = ROOT / "static" / "uploads" / "products"
        await run_in_threadpool(folder.mkdir, parents=True, exist_ok=True)
        await run_in_threadpool((folder / filename).write_bytes, content)
        image_url = f"/static/uploads/products/{filename}"

    new_product = Product(
        business_id=user.business_id,
        name=name,
        sku=sku,
        unit_cost=unit_cost,
        stock=total_stock,
        variants=json.dumps(variants) if variants else None,
        image_url=image_url
    )
    db.add(new_product)
    await db.commit()
    await log_action(db, user.business_id, user.id, "Додано товар", f"Додано товар '{name}' на склад.")

    return RedirectResponse("/admin/finance?msg=added", status_code=303)

@router.post("/delete-product")
async def delete_product(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager"]:
        return RedirectResponse("/", status_code=303)
    
    product = await db.get(Product, id)
    if product and product.business_id == user.business_id:
        await db.delete(product)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено товар", f"Видалено товар '{product.name}' зі складу.")

    return RedirectResponse("/admin/finance?msg=deleted", status_code=303)

@router.get("/chats", response_class=HTMLResponse)
async def chats_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager", "master"]: return RedirectResponse("/", status_code=303)
    
    content = f"""
    <div class="glass-card p-0 overflow-hidden d-flex" style="height: 75vh; border-radius: 32px;">
        <!-- Sidebar List -->
        <div style="width: 320px; border-right: 1px solid var(--glass-border); display: flex; flex-direction: column; background: rgba(0,0,0,0.2);">
            <div class="p-4 border-bottom" style="border-color: var(--glass-border) !important;">
                <h5 class="fw-800 text-white m-0"><i class="fas fa-comments text-primary me-2"></i>Діалоги</h5>
            </div>
            <div id="chat-list" class="overflow-auto flex-grow-1 p-3 d-flex flex-column gap-2" style="scrollbar-width: none;">
                <div class="text-center p-4 text-muted small"><i class="fas fa-spinner fa-spin mb-2"></i><br>Завантаження...</div>
            </div>
        </div>
        
        <!-- Main Chat Window -->
        <div class="flex-grow-1 d-flex flex-column position-relative bg-transparent">
            <!-- Chat Header -->
            <div id="chat-header" class="p-3 border-bottom d-flex align-items-center justify-content-between" style="border-color: var(--glass-border) !important; background: rgba(255,255,255,0.02);">
                <div class="d-flex align-items-center gap-3">
                    <div id="chat-avatar" class="rounded-circle d-flex align-items-center justify-content-center text-white fw-bold" style="width: 44px; height: 44px; background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink)); display: none !important;"></div>
                    <div>
                        <h6 id="chat-title" class="fw-800 text-white m-0">Оберіть діалог</h6>
                        <small id="chat-subtitle" class="text-muted opacity-75">Зі списку ліворуч</small>
                    </div>
                </div>
                <div id="chat-actions" style="display: none;">
                    <span class="badge bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25 px-3 py-2" id="chat-source-badge"></span>
                </div>
            </div>
            
            <!-- Chat Messages -->
            <div id="chat-messages" class="flex-grow-1 p-4 overflow-auto d-flex flex-column gap-3" style="background: rgba(0,0,0,0.15);">
                <div class="text-center m-auto text-muted opacity-50">
                    <i class="fas fa-comment-dots fa-4x mb-3"></i>
                    <h5 class="fw-bold">Тут буде історія листування</h5>
                </div>
            </div>
            
            <!-- Input Area -->
            <div id="chat-input-area" class="p-3 border-top" style="border-color: var(--glass-border) !important; background: rgba(255,255,255,0.02); display: none;">
                <form id="chat-form" class="d-flex gap-2" onsubmit="sendChatMessage(event)">
                    <input type="hidden" id="current_session_id">
                    <input type="text" id="message_input" class="glass-input flex-grow-1" placeholder="Введіть повідомлення як адміністратор..." autocomplete="off" required>
                    <button type="submit" class="btn-primary-glow px-4 py-2" style="border-radius: 16px;"><i class="fas fa-paper-plane"></i></button>
                </form>
            </div>
        </div>
    </div>
    """
    scripts = """
    <script>
    let activeSessionId = null;
    
    async function loadSessions() {
        try {
            const res = await fetch('/admin/api/chat-sessions');
            const data = await res.json();
            const list = document.getElementById('chat-list');
            list.innerHTML = '';
            
            if(data.length === 0) {
                list.innerHTML = '<div class="text-center p-4 text-muted small">Немає активних діалогів</div>';
                return;
            }
            
            data.forEach(s => {
                const isTg = s.source.includes('Telegram');
                const icon = isTg ? '<i class="fab fa-telegram text-info"></i>' : '<i class="fas fa-globe text-primary"></i>';
                const activeClass = s.id === activeSessionId ? 'active' : '';
                
                const item = document.createElement('div');
                item.className = 'chat-list-item ' + activeClass;
                item.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-bold text-white text-truncate">${icon} Клієнт</span>
                        <span class="small text-muted" style="font-size: 10px;"></span>
                    </div>
                    <div class="small text-muted text-truncate" data-i18n-ignore></div>`;
                item.querySelector('.small').textContent = s.time;
                item.lastElementChild.textContent = s.text;
                item.addEventListener('click', () => openChat(s.id, s.source));
                list.appendChild(item);
            });
        } catch(e) {
            console.error('Error loading sessions', e);
        }
    }
    
    async function openChat(sessionId, source) {
        activeSessionId = sessionId;
        document.getElementById('current_session_id').value = sessionId;
        document.getElementById('chat-avatar').style.setProperty('display', 'flex', 'important');
        document.getElementById('chat-avatar').innerHTML = '<i class="fas fa-user"></i>';
        document.getElementById('chat-title').innerText = 'Діалог з клієнтом';
        document.getElementById('chat-subtitle').innerText = 'ID: ' + sessionId.substring(0, 12) + '...';
        
        const badge = document.getElementById('chat-source-badge');
        badge.innerHTML = source.includes('Telegram') ? '<i class="fab fa-telegram me-1"></i> Telegram' : '<i class="fas fa-globe me-1"></i> Віджет';
        document.getElementById('chat-actions').style.display = 'block';
        document.getElementById('chat-input-area').style.display = 'block';
        
        loadSessions(); // Re-render list to highlight active
        
        const msgContainer = document.getElementById('chat-messages');
        msgContainer.innerHTML = '<div class="text-center m-auto text-muted"><i class="fas fa-spinner fa-spin fa-2x mb-2"></i></div>';
        
        try {
            const res = await fetch(`/admin/api/chat-history/${encodeURIComponent(sessionId)}`);
            const messages = await res.json();
            msgContainer.innerHTML = '';
            
            messages.forEach(m => {
                const isUser = m.role === 'user';
                const align = isUser ? 'align-self-start' : 'align-self-end';
                const bubbleClass = isUser ? 'user' : 'assistant';
                const senderName = isUser ? 'Клієнт' : 'AI / Менеджер';
                
                msgContainer.innerHTML += `
                <div class="d-flex flex-column ${align}" style="max-width: 80%;">
                    <span class="small text-muted mb-1 px-2" style="font-size: 10px;">${senderName} • ${m.time}</span>
                    <div class="chat-bubble ${bubbleClass}">${m.content}</div>
                </div>`;
            });
            msgContainer.scrollTop = msgContainer.scrollHeight;
        } catch(e) {
            msgContainer.innerHTML = '<div class="text-center text-danger">Помилка завантаження</div>';
        }
    }
    
    async function sendChatMessage(e) {
        e.preventDefault();
        const input = document.getElementById('message_input');
        const sessionId = document.getElementById('current_session_id').value;
        const text = input.value.trim();
        if(!text) return;
        
        input.value = '';
        const msgContainer = document.getElementById('chat-messages');
        msgContainer.innerHTML += `
        <div class="d-flex flex-column align-self-end" style="max-width: 80%;">
            <span class="small text-muted mb-1 px-2" style="font-size: 10px;">Ви • Щойно</span>
            <div class="chat-bubble assistant" data-i18n-ignore></div>
        </div>`;
        msgContainer.lastElementChild.querySelector(".chat-bubble").textContent = text;
        msgContainer.scrollTop = msgContainer.scrollHeight;
        
        let f = new FormData();
        f.append('session_id', sessionId);
        f.append('message', text);
        await fetch('/admin/api/chat-send', {method: 'POST', body: f});
    }
    
    document.addEventListener('DOMContentLoaded', () => {
        loadSessions();
        setInterval(loadSessions, 15000); // Auto-refresh list
    });
    </script>
    """
    return get_layout(content, user, "chats", scripts)

@router.get("/api/chat-sessions")
async def api_chat_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return []
    logs = (await db.execute(select(ChatLog).where(ChatLog.business_id == user.business_id).order_by(desc(ChatLog.created_at)).limit(300))).scalars().all()
    sessions = {}
    for log in logs:
        if log.user_identifier not in sessions:
            source = "Telegram" if log.user_identifier.startswith("tg_") else ("Web Віджет" if log.user_identifier.startswith("web_") else "Чат")
            sessions[log.user_identifier] = {
                "id": log.user_identifier,
                "source": source,
                "text": log.content[:45] + "..." if len(log.content) > 45 else log.content,
                "time": log.created_at.strftime('%H:%M'),
                "timestamp": log.created_at.timestamp()
            }
    return sorted(sessions.values(), key=lambda x: x["timestamp"], reverse=True)

@router.get("/api/chat-history/{session_id}")
async def api_chat_history(session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return []
    logs = (await db.execute(select(ChatLog).where(and_(ChatLog.business_id == user.business_id, ChatLog.user_identifier == session_id)).order_by(ChatLog.created_at))).scalars().all()
    return [{"role": l.role, "content": html.escape(l.content), "time": l.created_at.strftime('%H:%M')} for l in logs]

@router.post("/api/chat-send")
async def api_chat_send(session_id: str = Form(...), message: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or not user.business_id or not message.strip() or len(message) > 4096:
        return {"success": False}
    session_exists = await db.scalar(select(ChatLog.id).where(
        ChatLog.business_id == user.business_id, ChatLog.user_identifier == session_id,
    ).limit(1))
    if session_exists is None:
        return {"success": False}
    chat = ChatLog(business_id=user.business_id, user_identifier=session_id, role="assistant", content=f"👨‍💻 [Менеджер]: {message}")
    db.add(chat)
    await db.commit()
    if session_id.startswith("tg_"):
        biz = await db.get(Business, user.business_id)
        if biz and biz.telegram_token:
            chat_id = session_id.replace("tg_", "")
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage", json={"chat_id": chat_id, "text": message})
            except Exception: pass
    return {"success": True}


@router.get("/calendar-data")
async def get_calendar_data(start: Optional[str] = None, end: Optional[str] = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: 
        return []

    is_limited_master = False
    if user.role == "master":
        m_record = await db.get(Master, user.master_id)
        if not m_record or m_record.role == "Експерт":
            is_limited_master = True

    filters = [Appointment.business_id == user.business_id, Appointment.status != 'cancelled']
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        range_start = datetime.fromisoformat(start).replace(tzinfo=None) if start else now.replace(day=1)
        range_end = datetime.fromisoformat(end).replace(tzinfo=None) if end else (range_start.replace(day=28)+timedelta(days=4)).replace(day=1)
    except ValueError:
        return []
    if range_end <= range_start or (range_end-range_start).days > 93:
        return []
    filters.extend([Appointment.appointment_time >= range_start, Appointment.appointment_time < range_end])
    stmt = select(Appointment.appointment_time).where(and_(*filters))
    res = await db.execute(stmt)
    appts_datetimes = res.scalars().all()
    
    unique_dates = {a.strftime('%Y-%m-%d') for a in appts_datetimes}
    
    return [{"date": d} for d in sorted(unique_dates)]

@router.get("/day-details")
async def get_day_details(date: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: 
        return []
    try:
        dt = datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return []
    
    day_start = dt.replace(hour=0, minute=0, second=0)
    day_end = day_start + timedelta(days=1)

    is_limited_master = False
    if user.role == "master":
        m_record = await db.get(Master, user.master_id)
        if not m_record or m_record.role == "Експерт":
            is_limited_master = True

    filters = [
        Appointment.business_id == user.business_id,
        Appointment.status != 'cancelled',
        Appointment.appointment_time >= day_start,
        Appointment.appointment_time < day_end
    ]
    if is_limited_master:
        filters.append(Appointment.master_id == user.master_id)

    stmt = select(Appointment).options(joinedload(Appointment.customer)).where(and_(*filters)).order_by(Appointment.appointment_time)
    
    res = await db.execute(stmt)
    appts = res.scalars().all()
    
    status_map = {"confirmed": "Очікується", "completed": "Виконано", "cancelled": "Скасовано"}
    
    return [{"time": a.appointment_time.strftime('%H:%M'), "customer": a.customer.name if a.customer else "Гість", "service": a.service_type, "status": status_map.get(a.status, a.status)} for a in appts]


@router.get("/bot-integration", response_class=HTMLResponse)
async def bot_integration_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager"]: return RedirectResponse("/", status_code=303)
    
    branches_data = []
    if user.role == "owner" and user.business and user.business.parent_id is None:
        branches = (await db.execute(select(Business).where(Business.parent_id == user.business_id))).scalars().all()
        branches_data = [{"id": b.id, "name": b.name} for b in branches]
    
    all_biz_ids = [user.business_id] + [b["id"] for b in branches_data]
    ints = (await db.execute(select(Integration).where(Integration.business_id.in_(all_biz_ids)).order_by(desc(Integration.id)))).scalars().all()
    
    my_ints = []
    for i in ints:
        biz_name = "Головний офіс"
        if i.business_id != user.business_id:
            biz_name = next((b["name"] for b in branches_data if b["id"] == i.business_id), "Філія")
            
        my_ints.append({
            "id": i.id,
            "provider": i.provider,
            "name": i.name,
            "token": i.token or "",
            "ext_id": i.ext_id or "",
            "is_active": i.is_active,
            "business_id": i.business_id,
            "business_name": biz_name
        })
        
    my_ints_json = json.dumps(my_ints).replace("<", "\\u003c")
    branches_json = json.dumps(branches_data).replace("<", "\\u003c")

    content = f"""
    <div class="glass-card p-4 p-md-5 mb-4">
        <div class="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-3">
            <div>
                <h4 class="fw-800 text-white mb-2"><i class="fas fa-plug text-primary me-2"></i>Каталог Інтеграцій</h4>
                <p class="text-muted m-0">Підключіть улюблені сервіси для автоматизації бізнесу</p>
            </div>
            <div class="search-box position-relative" style="width: 300px;">
                <i class="fas fa-search"></i>
                <input type="text" id="intSearch" class="glass-input ps-5" placeholder="Пошук сервісів..." onkeyup="filterIntegrations()">
            </div>
        </div>
        
        <ul class="nav nav-pills mb-4" id="intTabs" role="tablist">
            <li class="nav-item"><button class="nav-link active" data-bs-toggle="pill" data-bs-target="#tab-my-ints">Мої підключення</button></li>
            <li class="nav-item"><button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-catalog">Каталог сервісів</button></li>
        </ul>

        <div class="tab-content">
            <div class="tab-pane fade show active" id="tab-my-ints">
                <div class="row g-3" id="my-integrations-grid"></div>
            </div>
            <div class="tab-pane fade" id="tab-catalog">
                <div class="d-flex gap-2 mb-4 overflow-auto pb-2" style="scrollbar-width: none;">
                    <button class="btn-glass active category-btn" data-cat="all" onclick="filterIntegrationsCat('all')">Усі сервіси</button>
                    <button class="btn-glass category-btn" data-cat="crm" onclick="filterIntegrationsCat('crm')">CRM</button>
                    <button class="btn-glass category-btn" data-cat="msg" onclick="filterIntegrationsCat('msg')">Месенджери</button>
                    <button class="btn-glass category-btn" data-cat="pay" onclick="filterIntegrationsCat('pay')">Платежі</button>
                </div>
                <div class="row g-3" id="integrations-grid"></div>
            </div>
        </div>
    </div>
    """
    scripts = """
    <script>
    const myIntegrations = __MY_INTS__;


    const catalog = [
        {id: 'altegio', name: 'Altegio (Yclients)', cat: 'crm', icon: 'fa-calendar-check', color: '#ff5722'},
        {id: 'beauty_pro', name: 'BeautyPro', cat: 'crm', icon: 'fa-spa', color: '#e91e63'},
        {id: 'cleverbox', name: 'Cleverbox', cat: 'crm', icon: 'fa-box', color: '#9c27b0'},
        {id: 'easyweek', name: 'EasyWeek', cat: 'crm', icon: 'fa-calendar-week', color: '#2196f3'},
        {id: 'integrica', name: 'Integrica', cat: 'crm', icon: 'fa-network-wired', color: '#00bcd4'},
        {id: 'wins', name: 'WINS', cat: 'crm', icon: 'fa-trophy', color: '#009688'},
        {id: 'appointer', name: 'Appointer', cat: 'crm', icon: 'fa-hand-pointer', color: '#4caf50'},
        {id: 'trendis', name: 'Trendis', cat: 'crm', icon: 'fa-chart-line', color: '#8bc34a'},
        {id: 'miopane', name: 'MioPane', cat: 'crm', icon: 'fa-bread-slice', color: '#ff9800'},
        {id: 'clinica_web', name: 'Clinica Web', cat: 'crm', icon: 'fa-clinic-medical', color: '#00bcd4'},
        {id: 'doctor_eleks', name: 'Doctor Eleks', cat: 'crm', icon: 'fa-user-md', color: '#3f51b5'},
        {id: 'uspacy', name: 'uSpacy', cat: 'crm', icon: 'fa-layer-group', color: '#00bcd4'},

        {id: 'telegram', name: 'Telegram (Bot API)', cat: 'msg', icon: 'fa-telegram', color: '#0088cc'},
        {id: 'instagram', name: 'Instagram Direct', cat: 'msg', icon: 'fa-instagram', color: '#e1306c'},
        {id: 'whatsapp', name: 'WhatsApp Business API', cat: 'msg', icon: 'fa-whatsapp', color: '#25d366'},
        {id: 'facebook', name: 'Facebook Messenger', cat: 'msg', icon: 'fa-facebook-messenger', color: '#0084ff'},
        {id: 'viber', name: 'Viber Chatbots', cat: 'msg', icon: 'fa-viber', color: '#665cac'},

        {id: 'turbosms', name: 'TurboSMS', cat: 'sms', icon: 'fa-comment-sms', color: '#f44336'},
        {id: 'binotel', name: 'Binotel', cat: 'sms', icon: 'fa-phone-alt', color: '#2196f3'},
        {id: 'ringostat', name: 'Ringostat', cat: 'sms', icon: 'fa-headset', color: '#4caf50'},
        {id: 'phonet', name: 'Phonet', cat: 'sms', icon: 'fa-phone-volume', color: '#ff9800'},
        {id: 'twilio', name: 'Twilio', cat: 'sms', icon: 'fa-sms', color: '#f44336'},
        {id: 'esputnik', name: 'eSputnik', cat: 'sms', icon: 'fa-paper-plane', color: '#673ab7'},

        {id: 'monobank', name: 'Monobank', cat: 'pay', icon: 'fa-credit-card', color: '#000000'},
        {id: 'liqpay', name: 'LiqPay', cat: 'pay', icon: 'fa-money-bill-wave', color: '#7cb342'},
        {id: 'wayforpay', name: 'WayForPay', cat: 'pay', icon: 'fa-wallet', color: '#2196f3'},
        {id: 'fondy', name: 'Fondy', cat: 'pay', icon: 'fa-file-invoice-dollar', color: '#e91e63'},
        {id: 'stripe', name: 'Stripe', cat: 'pay', icon: 'fa-cc-stripe', color: '#6772e5'},

        {id: 'groq', name: 'Groq API (Llama)', cat: 'ai', icon: 'fa-microchip', color: '#ff5722'},
        {id: 'openai', name: 'OpenAI (GPT)', cat: 'ai', icon: 'fa-robot', color: '#10a37f'},
        {id: 'google_maps', name: 'Google Maps (Відгуки)', cat: 'ai', icon: 'fa-map-marked-alt', color: '#ea4335'}
    ];
    
    let currentCat = 'all';
    
    const currentBizId = __BIZ_ID__;
    const branchesData = __BRANCHES__;
    
    function getBranchSelectHTML(selectedId = currentBizId) {
        if (branchesData.length === 0) return '';
        let options = `<option value="${currentBizId}" ${selectedId == currentBizId ? 'selected' : ''}>Головний офіс</option>`;
        branchesData.forEach(b => {
            options += `<option value="${b.id}" ${selectedId == b.id ? 'selected' : ''}>${b.name}</option>`;
        });
        return `
            <label class="form-label text-white-50">Локація (Філія)</label>
            <select name="target_business_id" class="form-select mb-3">${options}</select>
        `;
    }
    
    function renderMyIntegrations() {
        const grid = document.getElementById('my-integrations-grid');
        grid.innerHTML = '';
                if (myIntegrations.length === 0) {
            grid.innerHTML = '<div class="col-12 text-center py-5 text-muted">У вас ще немає підключених інтеграцій. Перейдіть до каталогу.</div>';
            return;
        }
            myIntegrations.forEach(int => {
            const meta = catalog.find(c => c.id === int.provider) || {name: int.provider, icon: 'fa-plug', color: '#fff'};
            const iconClass = meta.icon.startsWith('fa-') ? (['fa-telegram', 'fa-instagram', 'fa-whatsapp', 'fa-viber'].includes(meta.icon) ? 'fab ' + meta.icon : 'fas ' + meta.icon) : meta.icon;
            const activeBadge = int.is_active ? `<span class="badge bg-success ms-2" style="font-size: 9px;">Увімк</span>` : `<span class="badge bg-secondary ms-2" style="font-size: 9px;">Вимк</span>`;
            const borderStyle = int.is_active ? `border: 1px solid rgba(52,211,153,0.3); background: rgba(255,255,255,0.04);` : `border: 1px solid var(--glass-border);`;
            

            grid.innerHTML += `
                <div class="col-xl-4 col-lg-6 col-md-6 col-sm-12">
                    <div class="glass-card p-3 d-flex align-items-center gap-3" style="border-radius: 16px; ${borderStyle}">
                        <div style="width: 48px; height: 48px; border-radius: 12px; background: ${meta.color}20; color: ${meta.color}; display: flex; align-items: center; justify-content: center; font-size: 20px;">
                            <i class="${iconClass}"></i>
                        </div>
                        <div class="min-w-0 flex-grow-1" style="cursor: pointer;" onclick="openConfig('${int.id}')">
                            <h6 class="mb-1 text-white fw-bold text-truncate">${int.name}${activeBadge}</h6>
                            <div class="small opacity-50 text-truncate" style="font-size: 11px;">${meta.name} • ${int.business_name}</div>
                        </div>
                        <div class="d-flex gap-2">
                            <button class="btn btn-glass btn-sm px-2 py-1" onclick="openConfig('${int.id}')"><i class="fas fa-edit text-info"></i></button>
                            <form action="/admin/delete-integration" method="post" style="display:inline" onsubmit="return confirm('Видалити інтеграцію?');">
                                <input type="hidden" name="id" value="${int.id}">
                                <button class="btn btn-glass btn-sm px-2 py-1"><i class="fas fa-trash text-danger"></i></button>
                            </form>
                        </div>
                    </div>
                </div>
            `;
        });
    }

        function renderCatalog(searchQuery = '') {
        const grid = document.getElementById('integrations-grid');
        grid.innerHTML = '';
        
        catalog.forEach(int => {
            if(currentCat !== 'all' && int.cat !== currentCat) return;
            if(searchQuery && !int.name.toLowerCase().includes(searchQuery.toLowerCase())) return;
            
            let iconClass = int.icon.startsWith('fa-') ? (['fa-telegram', 'fa-instagram', 'fa-whatsapp', 'fa-viber'].includes(int.icon) ? 'fab ' + int.icon : 'fas ' + int.icon) : int.icon;
            
            grid.innerHTML += `
                <div class="col-xl-4 col-lg-6 col-md-6 col-sm-12">
                    <div class="glass-card p-3 d-flex align-items-center gap-3" style="cursor: pointer; border-radius: 16px; border: 1px solid var(--glass-border);" onclick="openNewConfig('${int.id}', '${int.name}')">
                        <div style="width: 48px; height: 48px; border-radius: 12px; background: ${int.color}20; color: ${int.color}; display: flex; align-items: center; justify-content: center; font-size: 20px;">
                            <i class="${iconClass}"></i>
                        </div>
                        <div class="min-w-0 flex-grow-1">
                            <h6 class="mb-1 text-white fw-bold text-truncate">${int.name}</h6>
                            <div class="small opacity-50 text-truncate" style="font-size: 11px;">Натисніть щоб додати</div>
                        </div>
                        <i class="fas fa-plus opacity-50 ms-2 text-primary"></i>
                    </div>
                </div>
            `;
        });
    }
    
    
    function filterIntegrationsCat(cat) {
        currentCat = cat;
        document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
        document.querySelector(`.category-btn[data-cat="${cat}"]`).classList.add('active');
        renderCatalog(document.getElementById('intSearch').value);
    }
    
    let intSearchTimeout;
    function filterIntegrations() {
        clearTimeout(intSearchTimeout);
        intSearchTimeout = setTimeout(() => {
            const q = document.getElementById('intSearch').value;
            renderCatalog(q);
        }, 300);
    }
    
    function openNewConfig(providerId, providerName) {


        Swal.fire({
            title: `Нове підключення: ${providerName}`,
            html: `
                <form id="integrationForm" action="/admin/save-integration" method="post" class="text-start mt-3">
                    <input type="hidden" name="integration_id" value="">
                    <input type="hidden" name="provider" value="${providerId}">
                    
                    ${getBranchSelectHTML(currentBizId)}
                    
                    <label class="form-label text-white-50">Назва (для себе)</label>
                    <input type="text" name="name" class="glass-input mb-3" placeholder="Мій ${providerName}" value="${providerName} 1" required>

                    <div class="form-check form-switch mb-3">
                        <input class="form-check-input" type="checkbox" name="is_active" id="intActive" value="true" checked>
                        <label class="form-check-label text-white" for="intActive">Активувати цю інтеграцію</label>
                    </div>
                    <label class="form-label text-white-50">API Token / Secret Key</label>
                    <input type="text" name="token" class="glass-input mb-3" placeholder="Введіть токен...">
                    
                    <label class="form-label text-white-50">Додатковий ID (Company / Location ID)</label>
                    <input type="text" name="ext_id" class="glass-input" placeholder="Введіть ID...">
                </form>
            `,
            background: 'rgba(20, 20, 25, 0.95)',
            color: '#fff',
            customClass: { popup: 'glass-card' },
            showCancelButton: true,
            confirmButtonText: 'Додати',
            cancelButtonText: 'Скасувати',
            preConfirm: () => {
                document.getElementById('integrationForm').submit();
            }
        });
    }
    

    function openConfig(id) {
        const data = myIntegrations.find(i => i.id == id);
        if(!data) return;
        const meta = catalog.find(c => c.id === data.provider) || {name: data.provider};
        
        Swal.fire({
            title: `Редагування: ${data.name}`,
            html: `
                <form id="integrationForm" action="/admin/save-integration" method="post" class="text-start mt-3">
                    <input type="hidden" name="integration_id" value="${data.id}">
                    <input type="hidden" name="provider" value="${data.provider}">
                    
                    ${getBranchSelectHTML(data.business_id || currentBizId)}
                    
                    <label class="form-label text-white-50">Назва (для себе)</label>
                    <input type="text" name="name" class="glass-input mb-3" value="${data.name}" required>

                    <div class="form-check form-switch mb-3">
                        <input class="form-check-input" type="checkbox" name="is_active" id="intActive" value="true" ${data.is_active ? 'checked' : ''}>
                        <label class="form-check-label text-white" for="intActive">Активувати</label>
                    </div>
                    
                    <label class="form-label text-white-50">API Token / Secret Key</label>
                    <input type="text" name="token" class="glass-input mb-3" value="${data.token}">
                    
                    <label class="form-label text-white-50">Додатковий ID (Company / Location ID)</label>
                    <input type="text" name="ext_id" class="glass-input" value="${data.ext_id}">
                </form>
            `,
            background: 'rgba(20, 20, 25, 0.95)',
            color: '#fff',
            customClass: { popup: 'glass-card' },
            showCancelButton: true,
            confirmButtonText: 'Зберегти',
            cancelButtonText: 'Скасувати',
            preConfirm: () => {
                document.getElementById('integrationForm').submit();
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        renderMyIntegrations();
        renderCatalog();
    });
    </script>
    """
    scripts = scripts.replace("__MY_INTS__", my_ints_json).replace("__BIZ_ID__", str(user.business_id)).replace("__BRANCHES__", branches_json)
    return get_layout(content, user, "bot", scripts=scripts)


@router.post("/save-integration")
async def save_integration(
    request: Request,
    integration_id: Optional[str] = Form(None),
    provider: str = Form(...),
    name: str = Form(...),
    is_active: bool = Form(False),
    token: Optional[str] = Form(None),
    ext_id: Optional[str] = Form(None),
    target_business_id: Optional[int] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role not in ["owner", "admin", "manager"]: return RedirectResponse("/", status_code=303)
    
    if ext_id and ext_id.lower().startswith(("http://", "https://")):
        try:
            await validate_public_url(ext_id)
        except ValueError:
            return RedirectResponse("/admin/bot-integration?error=unsafe_url", status_code=303)
    biz_id_to_use = user.business_id
    if target_business_id and target_business_id != user.business_id:
        if user.role == "owner":
            branch = await db.get(Business, target_business_id)
            if branch and branch.parent_id == user.business_id:
                biz_id_to_use = target_business_id
            else:
                return RedirectResponse("/admin/bot-integration", status_code=303)
                
    if integration_id:
        integration = await db.get(Integration, int(integration_id))
        if not integration:
            return RedirectResponse("/admin/bot-integration", status_code=303)
            
        is_allowed = False
        if integration.business_id == user.business_id:
            is_allowed = True
        elif user.role == "owner":
            branch = await db.get(Business, integration.business_id)
            if branch and branch.parent_id == user.business_id:
                is_allowed = True
                
        if not is_allowed:
            return RedirectResponse("/admin/bot-integration", status_code=303)
            
        integration.name = name
        integration.is_active = is_active
        integration.token = token
        integration.ext_id = ext_id
        integration.business_id = biz_id_to_use
    else:
        integration = Integration(
            business_id=biz_id_to_use,
            provider=provider,
            name=name,
            is_active=is_active,
            token=token,
            ext_id=ext_id
        )
        db.add(integration)
        
    await db.commit()
    await db.refresh(integration)
    
    biz_to_update = await db.get(Business, biz_id_to_use)
    if biz_to_update:
        active_ints = (await db.execute(select(Integration).where(and_(Integration.business_id == biz_id_to_use, Integration.is_active == True)))).scalars().all()
        biz_to_update.integration_system = ",".join(set([i.provider for i in active_ints]))
        
        ptg = next((i for i in active_ints if i.provider == 'telegram'), None)
        biz_to_update.telegram_token = ptg.token if ptg else None
        biz_to_update.telegram_enabled = bool(ptg)
        
        pa = next((i for i in active_ints if i.provider == 'altegio'), None)
        if pa: biz_to_update.altegio_token = pa.token; biz_to_update.altegio_company_id = pa.ext_id
        pb = next((i for i in active_ints if i.provider == 'beauty_pro'), None)
        if pb: biz_to_update.beauty_pro_token = pb.token; biz_to_update.beauty_pro_location_id = pb.ext_id
        psms = next((i for i in active_ints if i.provider == 'turbosms'), None)
        if psms: biz_to_update.sms_token = psms.token; biz_to_update.sms_sender_id = psms.ext_id
        pgr = next((i for i in active_ints if i.provider == 'groq'), None)
        if pgr: biz_to_update.groq_api_key = pgr.token
        await db.commit()
        
    if provider == "telegram" and token:
        base_url = str(request.base_url).rstrip('/')
        if base_url.startswith("http://"): base_url = base_url.replace("http://", "https://")
        webhook_url = f"{base_url}/webhook/telegram/{biz_id_to_use}"
        try:
            async with httpx.AsyncClient() as client:
                if is_active:
                    secret_token = hmac.new(SECRET_KEY.encode(), f"telegram:{biz_id_to_use}".encode(), hashlib.sha256).hexdigest()
                    await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url": webhook_url, "secret_token": secret_token})
                else:
                    await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except Exception: pass
        
    await log_action(db, biz_id_to_use, user.id, "Збережено інтеграцію", f"Інтеграцію '{name}' збережено.")
    return RedirectResponse("/admin/bot-integration?msg=saved", status_code=303)


@router.post("/delete-integration")
async def delete_integration(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "admin", "manager"]: return RedirectResponse("/", status_code=303)
    
    integration = await db.get(Integration, id)
    if integration:
        is_allowed = False
        if integration.business_id == user.business_id:
            is_allowed = True
        elif user.role == "owner":
            branch = await db.get(Business, integration.business_id)
            if branch and branch.parent_id == user.business_id:
                is_allowed = True
                
        if is_allowed:
            biz_id = integration.business_id
            if integration.provider == "telegram" and integration.token:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(f"https://api.telegram.org/bot{integration.token}/deleteWebhook")
                except Exception: pass
                
            await db.delete(integration)
            
            biz_to_update = await db.get(Business, biz_id)
            active_ints = (await db.execute(select(Integration).where(and_(Integration.business_id == biz_id, Integration.is_active == True)))).scalars().all()
            biz_to_update.integration_system = ",".join(set([i.provider for i in active_ints]))
            await db.commit()
            await log_action(db, biz_id, user.id, "Видалено інтеграцію", f"Інтеграцію '{integration.name}' видалено.")

    return RedirectResponse("/admin/bot-integration?msg=deleted", status_code=303)


@router.get("/help", response_class=HTMLResponse)
async def help_page(user: User = Depends(get_current_user)):
    if not user: return RedirectResponse("/", status_code=303)
    content = f"""
    <div class="glass-card p-4 p-md-5 mx-auto" style="max-width: 900px;">
        <div class="text-center mb-5">
            <div class="mb-4"><i class="fas fa-headset fa-3x text-success opacity-75"></i></div>
            <h4 class="fw-800 text-white mb-2">Довідковий центр (FAQ)</h4>
            <a href="https://t.me/SaaSDevelop" target="_blank" class="btn-primary-glow px-4 py-2 mt-3"><i class="fab fa-telegram me-2"></i>Написати в підтримку</a>
        </div>
        
        <div class="d-flex gap-2 mb-4 overflow-auto pb-2" style="scrollbar-width: none;" id="faq-categories">
            <button class="btn-glass active faq-cat-btn" onclick="filterFaq('all', this)">Всі</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('start', this)">🚀 Початок роботи</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('messengers', this)">📱 Месенджери</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('billing', this)">💰 Оплати</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('analytics', this)">📊 Аналітика</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('security', this)">🔒 Безпека</button>
        </div>
        
        <div class="search-box w-100 mb-4" style="max-width: 100%;">
            <i class="fas fa-search"></i>
            <input type="text" id="faqSearch" class="glass-input ps-5 w-100" placeholder="Пошук по базі знань..." onkeyup="searchFaq()">
        </div>
        
        <div class="accordion" id="faqAccordion" style="border-radius: 16px; overflow: hidden;">
            <!-- JS will populate this with many questions -->
        </div>
    </div>
    """
    scripts = """
    <style>
    #faqAccordion .accordion-item {
        background: rgba(255,255,255,0.02);
        border: 1px solid var(--glass-border);
        border-radius: 16px !important;
        margin-bottom: 12px;
        overflow: hidden;
    }
    #faqAccordion .accordion-button {
        background: transparent;
        color: #fff;
        font-weight: 600;
        box-shadow: none;
        padding: 16px 20px;
    }
    #faqAccordion .accordion-button:not(.collapsed) {
        background: rgba(255,255,255,0.05);
        color: var(--accent-primary);
    }
    #faqAccordion .accordion-button::after {
        filter: invert(1);
    }
    #faqAccordion .accordion-body {
        color: rgba(255,255,255,0.7);
        font-size: 14px;
        line-height: 1.6;
        padding: 20px;
        border-top: 1px solid rgba(255,255,255,0.05);
    }
    </style>
    <script>
    const faqs = [
    {
        "cat": "start",
        "q": "Створити запис",
        "a": "На сторінці огляду натисніть «Створити запис», заповніть контакт, послугу, дату й час та збережіть запис."
    },
    {
        "cat": "start",
        "q": "Додати послугу",
        "a": "У конфігурації відкрийте «Послуги» та введіть назву, ціну й тривалість."
    },
    {
        "cat": "analytics",
        "q": "Звіт за записами",
        "a": "У розділі «Звіти» оберіть дати. Там доступні дохід за завершеними записами, середня сума та експорт у CSV."
    },
    {
        "cat": "analytics",
        "q": "Склад та Товари",
        "a": "У розділі «Склад» можна додавати товари та варіанти. Товари із залишком до п’яти одиниць показано у звітах."
    },
    {
        "cat": "billing",
        "q": "Тариф та підключення",
        "a": "На сторінці реєстрації оберіть тариф і країну оплати. Після завантаження документів статус заявки можна переглянути на сторінці активації."
    },
    {
        "cat": "messengers",
        "q": "Клієнт не отримує SMS",
        "a": "Перевірте токен, ім’я відправника та баланс у TurboSMS. Для автоматичних нагадувань увімкніть SMS у налаштуваннях."
    },
    {
        "cat": "security",
        "q": "Блокування клієнта",
        "a": "У списку клієнтів натисніть «Заблокувати клієнта». Це обмежує самостійне бронювання та консультації ШІ для цього номера."
    },
    {
        "cat": "start",
        "q": "Демо SafeOrbit",
        "a": "На сторінці входу можна відкрити демо без пароля. Зміни зберігаються в окремій сесії, яка спливає після години бездіяльності."
    }
];

    let currentFaqCat = 'all';

    function renderFaqs(search = '') {
        const container = document.getElementById('faqAccordion');
        container.innerHTML = '';
        let html = '';
        let count = 0;
        
        faqs.forEach((faq, index) => {
            if(currentFaqCat !== 'all' && faq.cat !== currentFaqCat) return;
            const translate = window.SafeOrbitI18N?.translate || (text => text);
            if (search && ![faq.q, faq.a, translate(faq.q), translate(faq.a)]
                .some(text => text.toLowerCase().includes(search.toLowerCase()))) return;
            
            count++;
            html += `
                <div class="accordion-item">
                    <h2 class="accordion-header" id="heading${index}">
                        <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse${index}">
                            ${faq.q}
                        </button>
                    </h2>
                    <div id="collapse${index}" class="accordion-collapse collapse" data-bs-parent="#faqAccordion">
                        <div class="accordion-body">${faq.a}</div>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = count === 0 ? '<div class="text-center p-4 text-muted">За вашим запитом нічого не знайдено</div>' : html;
    }

    function filterFaq(cat, btn) {
        currentFaqCat = cat;
        document.querySelectorAll('.faq-cat-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderFaqs(document.getElementById('faqSearch').value);
    }

    let faqSearchTimeout;
    function searchFaq() {
        clearTimeout(faqSearchTimeout);
        faqSearchTimeout = setTimeout(() => {
            renderFaqs(document.getElementById('faqSearch').value);
        }, 300);
    }

    document.addEventListener('DOMContentLoaded', () => renderFaqs());
    </script>
    """
    return get_layout(content, user, "help", scripts=scripts)

@router.get("/updates", response_class=HTMLResponse)
async def updates_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return RedirectResponse("/", status_code=303)
    
    db_user = await db.get(User, user.id)
    if db_user:
        db_user.last_updates_view_at = datetime.now(UA_TZ).replace(tzinfo=None)
        await db.commit()

    updates = (await db.execute(select(SystemUpdate).order_by(desc(SystemUpdate.created_at)))).scalars().all()
    
    updates_html = ""
    for u in updates:
        date_str = u.created_at.strftime('%d.%m.%Y %H:%M')
        content_html = html.escape(u.content).replace('\n', '<br>')
        updates_html += f"""
        <div class="glass-card p-4 p-md-5 mb-4 position-relative overflow-hidden">
            <div class="position-absolute top-0 end-0 p-4 opacity-10">
                <i class="fas fa-bullhorn fa-4x text-primary"></i>
            </div>
            <div class="d-flex justify-content-between align-items-center mb-4 position-relative">
                <h5 class="fw-800 text-white m-0" style="font-size: 22px;">{html.escape(u.title)}</h5>
                <span class="badge bg-primary bg-opacity-20 text-primary border border-primary border-opacity-25 px-3 py-2">{date_str}</span>
            </div>
            <div class="text-white-50 position-relative" style="line-height: 1.7; font-size: 15px;">
                {content_html}
            </div>
        </div>
        """
        
    if not updates_html:
        updates_html = '<div class="text-center p-5 text-muted glass-card">Оновлень ще немає.</div>'
        
    content = f"""
    <div class="mx-auto" style="max-width: 800px;">
        <div class="text-center mb-5 mt-4">
            <div class="logo-icon mb-4" style="width: 72px; height: 72px; margin: 0 auto; background: rgba(52, 211, 153, 0.1); color: var(--success); font-size: 28px; border-radius: 20px;"><i class="fas fa-newspaper"></i></div>
            <h4 class="fw-800 text-white" style="font-size: 32px; letter-spacing: -1px;">Оновлення та Поради</h4>
            <p class="text-muted fw-500">Офіційні новини платформи, поради щодо роботи та інструкції</p>
        </div>
        {updates_html}
    </div>
    """
    return get_layout(content, user, "upd")

@router.get("/api/unread-updates")
async def api_unread_updates(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user: return {"count": 0}
    stmt = select(func.count(SystemUpdate.id))
    if user.last_updates_view_at:
        stmt = stmt.where(SystemUpdate.created_at > user.last_updates_view_at)
    count = await db.scalar(stmt)
    return {"count": count or 0}
