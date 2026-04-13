import html
import io
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import urllib.parse

import httpx
import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import and_, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import LABELS, UA_TZ
from database import get_db
from dependencies import get_current_user
from models import (ActionLog, Appointment, AppointmentConfirmation, Business, ChatLog, Customer,
                    CustomerSegment, GlobalPaymentSettings, Master, MasterService, 
                    MonthlyPaymentLog, NPSReview, Product, Service, User, SystemUpdate, Integration)
from ui import get_layout
from utils import hash_password, log_action

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/settings", response_class=HTMLResponse)
async def ai_settings_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "master"]: return RedirectResponse("/", status_code=303)
    biz = (await db.execute(select(Business).where(Business.id == user.business_id))).scalar_one_or_none()
    
    models = [("llama-3.3-70b-versatile", "AI-5.0.0-expert-version")]
    model_options = "".join([f'<option value="{m[0]}" {"selected" if biz.ai_model == m[0] else ""}>{m[1]}</option>' for m in models])

    masters = (await db.execute(select(Master).options(joinedload(Master.services)).where(Master.business_id == user.business_id))).unique().scalars().all()
    services = (await db.execute(select(Service).where(Service.business_id == user.business_id))).scalars().all()

    master_users = (await db.execute(select(User).where(and_(User.business_id == user.business_id, User.role == 'master')))).scalars().all()
    master_user_map = {u.master_id: u.username for u in master_users if u.master_id}

    l = LABELS.get(biz.type, LABELS["generic"])

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
        branches_tab_content = f"""
        <div class="tab-pane fade" id="pills-branches">
            <div class="row g-4"> 
                <div class="col-md-5">
                    <div class="glass-card p-4">
                        <h5 class="fw-800 text-white mb-4">Додати філію</h5>
                        <form action="/admin/add-branch" method="post">
                            <div class="mb-3"><input name="name" class="glass-input" placeholder="Назва філії (напр. 'На Подолі')" required></div>
                            <div class="mb-3"><input name="city" class="glass-input" placeholder="Місто (напр. Київ)" required></div>
                            <div class="mb-4"><input name="address" class="glass-input" placeholder="Адреса (напр. вул. Хрещатик, 1)" required></div>
                            <h6 class="fw-800 text-muted small mb-3">Акаунт для входу у філію</h6>
                            <div class="mb-3"><input name="login" class="glass-input" placeholder="Логін (телефон філії)" required></div>
                            <div class="mb-4"><input name="password" type="password" class="glass-input" placeholder="Пароль" required></div>
                            <button class="btn-primary-glow w-100 py-3">Створити філію</button>
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
    api_key_val = getattr(biz, 'api_key', None) or 'Ключ не згенеровано'
    api_tab_btn = '<li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#pills-api"><i class="fas fa-code me-2"></i>API</button></li>'
    api_tab_content = f"""
        <div class="tab-pane fade" id="pills-api">
            <div class="glass-card p-4 p-md-5" style="max-width: 800px;">
                <h5 class="fw-800 text-white mb-4">REST API для розробників</h5>
                <p class="small text-muted mb-4">Використовуйте цей ключ для інтеграції вашої CRM з іншими сервісами або власним сайтом.</p>
                <div class="mb-4">
                    <label class="form-label text-white">Ваш API Ключ</label>
                    <div class="input-group">
                        <input type="text" class="glass-input" value="{html.escape(api_key_val)}" readonly id="apiKeyInput" style="border-radius: 12px 0 0 12px;">
                        <button class="btn btn-glass" type="button" onclick="navigator.clipboard.writeText(document.getElementById('apiKeyInput').value); showToast('Ключ скопійовано!');" style="border-radius: 0; border-left: none; border-right: none;"><i class="fas fa-copy text-info"></i></button>
                        <form action="/admin/generate-api-key" method="post" class="m-0 d-inline-flex">
                            <button class="btn btn-glass" type="submit" style="border-radius: 0 12px 12px 0;" title="Згенерувати новий"><i class="fas fa-sync text-warning"></i></button>
                        </form>
                    </div>
                </div>
                <div class="p-4 rounded-4" style="background: rgba(255,255,255,0.02); border: 0.5px solid var(--glass-border);">
                    <h6 class="fw-bold text-white mb-3">Приклад використання (Python)</h6>
                    <pre class="text-info small m-0" style="white-space: pre-wrap; font-family: monospace;"><code>import requests\nheaders = {{"X-API-Key": "{api_key_val}"}}\nres = requests.get("https://ваш-домен/api/v1/appointments", headers=headers)\nprint(res.json())</code></pre>
                </div>
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
        new bootstrap.Modal(document.getElementById('createAccountModal')).show();
    }
    </script>
    """
    return get_layout(content, user, "set", scripts)

@router.get("/generator", response_class=HTMLResponse)
async def prompt_generator_page(user: User = Depends(get_current_user)):
    if not user or user.role != "owner": return RedirectResponse("/admin", status_code=303)
    
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
    if not user or user.role != "owner":
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
    if not user or user.role not in ["owner", "superadmin"]:
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
    if not user or user.role not in ["owner", "superadmin"]:
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
    if not user or user.role not in ["owner", "superadmin"]:
        return RedirectResponse("/", status_code=303)

    new_service = Service(business_id=user.business_id, name=name, price=price, duration=duration)
    db.add(new_service)
    await db.commit()
    await log_action(db, user.business_id, user.id, "Додано послугу", f"Додано послугу '{name}' ({price} грн, {duration} хв).")

    return RedirectResponse("/admin/settings?msg=added", status_code=303)


@router.post("/delete-service")
async def delete_service(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "superadmin"]:
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
    if not user or user.role not in ["owner", "superadmin"]:
        return RedirectResponse("/", status_code=303)

    master = await db.get(Master, id)
    if master and master.business_id == user.business_id:
        existing_user = await db.scalar(select(User).where(User.username == login))
        if existing_user:
            return RedirectResponse("/admin/settings?msg=login_exists", status_code=303)

        new_user = User(username=login, password=hash_password(password), role="master", business_id=user.business_id, master_id=master.id)
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

    new_branch = Business(name=name, city=city, address=address, parent_id=user.business_id, type=user.business.type, plan_type=user.business.plan_type)
    db.add(new_branch)
    await db.flush()
    await db.refresh(new_branch)

    new_user = User(username=login, password=hash_password(password), role="owner", business_id=new_branch.id)
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
    if not user or user.role != "owner":
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


@router.get("/klienci", response_class=HTMLResponse)
async def clients_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "master"]: return RedirectResponse("/", status_code=303)
    customers = (await db.execute(select(Customer).where(Customer.business_id == user.business_id).order_by(desc(Customer.id)))).scalars().all()
    
    rows = ""
    for c in customers:
        badge = "<span class='badge bg-danger bg-opacity-10 text-danger'>Заблоковано</span>" if getattr(c, 'is_blocked', False) else "<span class='badge bg-success bg-opacity-10 text-success'>Активний</span>"
        btn_icon = "fa-unlock text-success" if getattr(c, 'is_blocked', False) else "fa-ban text-danger"
        btn_title = "Розблокувати клієнта" if getattr(c, 'is_blocked', False) else "Заблокувати клієнта (Чорний список)"
        btn_edit = f"<button type='button' class='btn btn-glass btn-sm me-1' onclick=\"editCustomer({c.id}, '{html.escape(c.name or '')}', '{html.escape(c.phone_number or '')}', {c.discount_percent}, '{html.escape(c.notes or '')}')\" title='Редагувати профіль'><i class='fas fa-edit text-info'></i></button>"
        
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
        
    content = f"""
    <div class="glass-card p-4">
        <h5 class="fw-800 text-white mb-4"><i class="fas fa-users text-primary me-2"></i>База клієнтів</h5>
        <div class="table-responsive w-full overflow-x-auto whitespace-nowrap block">
            <table class="glass-table">
                <thead><tr><th>ID</th><th>Ім'я</th><th>Телефон</th><th>Знижка</th><th>Статус</th><th>Нотатки</th><th class="text-end">Дії</th></tr></thead>
                <tbody>{rows if rows else '<tr><td colspan="7" class="text-center py-5 text-muted">Клієнтів ще немає</td></tr>'}</tbody>
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
        new bootstrap.Modal(document.getElementById('editCustomerModal')).show();
    }
    </script>
    """
    return get_layout(content, user, "kli", scripts=scripts)


@router.post("/toggle-client-block")
async def toggle_client_block(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "master"]: 
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
    if not user or user.role not in ["owner", "master"]: 
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
async def finance_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    products = (await db.execute(select(Product).where(Product.business_id == user.business_id).order_by(desc(Product.id)))).scalars().all()
    
    rows = ""
    for p in products:
        variants_html = ""
        if p.variants:
            try:
                variants = json.loads(p.variants)
                variants_html = "<ul class='list-unstyled mb-0 small text-muted'>"
                for v in variants:
                    variants_html += f"<li>{v.get('color', '')} {v.get('size', '')}: {v.get('stock', 0)} шт.</li>"
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
                            <input name="unit_cost" type="number" step="0.01" class="glass-input" placeholder="0.00" required>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <label class="form-label">Фото товару</label>
                        <input type="file" name="image" class="form-control" accept="image/*">
                    </div>
                    
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
            <div class="col-3"><input name="variant_stock" type="number" class="glass-input" placeholder="К-сть" value="1"></div>
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
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
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
    if not user or user.role != "owner":
        return RedirectResponse("/", status_code=303)

    variants = []
    total_stock = 0
    for i in range(len(variant_color)):
        try:
            stock = int(variant_stock[i])
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
        os.makedirs("static/uploads/products", exist_ok=True)
        ext = image.filename.split('.')[-1] if '.' in image.filename else 'jpg'
        filepath = f"static/uploads/products/prod_{int(datetime.now().timestamp())}.{ext}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/{filepath}"

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
    if not user or user.role != "owner":
        return RedirectResponse("/", status_code=303)
    
    product = await db.get(Product, id)
    if product and product.business_id == user.business_id:
        await db.delete(product)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено товар", f"Видалено товар '{product.name}' зі складу.")

    return RedirectResponse("/admin/finance?msg=deleted", status_code=303)

@router.post("/generate-api-key")
async def generate_api_key(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner":
        return RedirectResponse("/", status_code=303)
    import secrets
    biz = await db.get(Business, user.business_id)
    if biz:
        biz.api_key = f"sk_live_{secrets.token_urlsafe(24)}"
        await db.commit()
        await log_action(db, user.business_id, user.id, "Генерація API ключа", "Згенеровано новий API ключ.")
    return RedirectResponse("/admin/settings?msg=saved", status_code=303)

@router.get("/chats", response_class=HTMLResponse)
async def chats_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role not in ["owner", "master"]: return RedirectResponse("/", status_code=303)
    
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
                
                list.innerHTML += `
                <div class="chat-list-item ${activeClass}" onclick="openChat('${s.id}', '${s.source}')">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-bold text-white text-truncate">${icon} Клієнт</span>
                        <span class="small text-muted" style="font-size: 10px;">${s.time}</span>
                    </div>
                    <div class="small text-muted text-truncate">${s.text}</div>
                </div>`;
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
            const res = await fetch(`/admin/api/chat-history/${sessionId}`);
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
            <div class="chat-bubble assistant">${text}</div>
        </div>`;
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
    if not user: return {"success": False}
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
async def get_calendar_data(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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

    stmt = select(Appointment.appointment_time).where(and_(*filters))
    res = await db.execute(stmt)
    appts_datetimes = res.scalars().all()
    
    unique_dates = {a.strftime('%Y-%m-%d') for a in appts_datetimes}
    
    return [{"date": d} for d in unique_dates]

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
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    ints = (await db.execute(select(Integration).where(Integration.business_id == user.business_id).order_by(desc(Integration.id)))).scalars().all()
    my_ints = []
    for i in ints:
        my_ints.append({
            "id": i.id,
            "provider": i.provider,
            "name": i.name,
            "token": i.token or "",
            "ext_id": i.ext_id or "",
            "is_active": i.is_active
        })
    my_ints_json = json.dumps(my_ints)

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
    const myIntegrations = {my_ints_json};


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
                            <div class="small opacity-50 text-truncate" style="font-size: 11px;">${meta.name}</div>
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
    
    function filterIntegrations() {
        const q = document.getElementById('intSearch').value;
        renderCatalog(q);
    }
    
    function openNewConfig(providerId, providerName) {


        Swal.fire({
            title: `Нове підключення: ${providerName}`,
            html: `
                <form id="integrationForm" action="/admin/save-integration" method="post" class="text-start mt-3">
                    <input type="hidden" name="integration_id" value="">
                    <input type="hidden" name="provider" value="${providerId}">
                    
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
    scripts = scripts.replace("{my_ints_json}", my_ints_json)
    return get_layout(content, user, "bot", scripts=scripts)


@router.post("/save-integration")
async def save_integration(
    request: Request,
    integration_id: Optional[str] = Form(None),
    provider: str = Form(...),
    name: str = Form(...),    is_active: bool = Form(False),
    token: Optional[str] = Form(None),
    ext_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    if integration_id:
        integration = await db.get(Integration, int(integration_id))
        if not integration or integration.business_id != user.business_id:
            return RedirectResponse("/admin/bot-integration", status_code=303)
        integration.name = name
        integration.is_active = is_active
        integration.token = token
        integration.ext_id = ext_id
    else:
        integration = Integration(
            business_id=user.business_id,
            provider=provider,
            name=name,
            is_active=is_active,
            token=token,
            ext_id=ext_id
        )
        db.add(integration)
        
    await db.commit()
    await db.refresh(integration)
    
    # Зворотна сумісність для webhook-сервісів (оновлюємо глобальні токени)
    biz = await db.get(Business, user.business_id)
    if biz:
        active_ints = (await db.execute(select(Integration).where(and_(Integration.business_id == user.business_id, Integration.is_active == True)))).scalars().all()
        biz.integration_system = ",".join(set([i.provider for i in active_ints]))
        
        ptg = next((i for i in active_ints if i.provider == 'telegram'), None)
        biz.telegram_token = ptg.token if ptg else None
        biz.telegram_enabled = bool(ptg)
        
        pa = next((i for i in active_ints if i.provider == 'altegio'), None)
        if pa: biz.altegio_token = pa.token; biz.altegio_company_id = pa.ext_id

        pb = next((i for i in active_ints if i.provider == 'beauty_pro'), None)
        if pb: biz.beauty_pro_token = pb.token; biz.beauty_pro_location_id = pb.ext_id

        psms = next((i for i in active_ints if i.provider == 'turbosms'), None)
        if psms: biz.sms_token = psms.token; biz.sms_sender_id = psms.ext_id

        pgr = next((i for i in active_ints if i.provider == 'groq'), None)
        if pgr: biz.groq_api_key = pgr.token

        await db.commit()    
    if provider == "telegram" and token:
        base_url = str(request.base_url).rstrip('/')
        if base_url.startswith("http://"): base_url = base_url.replace("http://", "https://")
        webhook_url = f"{base_url}/webhook/telegram/{user.business_id}"
        try:
            async with httpx.AsyncClient() as client:
                if is_active:
                    await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url": webhook_url})
                else:
                    await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except Exception: pass
        
        
    await log_action(db, user.business_id, user.id, "Збережено інтеграцію", f"Інтеграцію '{name}' збережено.")
    
    return RedirectResponse("/admin/bot-integration?msg=saved", status_code=303)


@router.post("/delete-integration")
async def delete_integration(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "owner": return RedirectResponse("/", status_code=303)
    
    integration = await db.get(Integration, id)
    if integration and integration.business_id == user.business_id:
        if integration.provider == "telegram" and integration.token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(f"https://api.telegram.org/bot{integration.token}/deleteWebhook")
            except Exception: pass
            
        await db.delete(integration)
        await db.commit()
        await log_action(db, user.business_id, user.id, "Видалено інтеграцію", f"Інтеграцію '{integration.name}' видалено.")

    return RedirectResponse("/admin/bot-integration?msg=deleted", status_code=303)


@router.get("/help", response_class=HTMLResponse)
async def help_page(user: User = Depends(get_current_user)):
    if not user: return RedirectResponse("/", status_code=303)
    content = f"""
    <div class="glass-card p-4 p-md-5 mx-auto" style="max-width: 900px;">
        <div class="text-center mb-5">
            <div class="mb-4"><i class="fas fa-headset fa-3x text-success opacity-75"></i></div>
            <h4 class="fw-800 text-white mb-2">Довідковий центр (FAQ)</h4>
            <p class="text-muted">База знань: 200+ відповідей на часті запитання</p>
            <a href="https://t.me/SaaSDevelop" target="_blank" class="btn-primary-glow px-4 py-2 mt-3"><i class="fab fa-telegram me-2"></i>Написати в підтримку</a>
        </div>
        
        <div class="d-flex gap-2 mb-4 overflow-auto pb-2" style="scrollbar-width: none;" id="faq-categories">
            <button class="btn-glass active faq-cat-btn" onclick="filterFaq('all', this)">Всі</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('start', this)">🚀 Початок роботи</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('ai', this)">🤖 Налаштування ШІ</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('integrations', this)">🔌 Інтеграції</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('messengers', this)">📱 Месенджери</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('voice', this)">📞 Голосовий ШІ</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('billing', this)">💰 Оплати</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('analytics', this)">📊 Аналітика</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('security', this)">🔒 Безпека</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('troubleshooting', this)">🆘 Вирішення проблем</button>
            <button class="btn-glass faq-cat-btn" onclick="filterFaq('pricing', this)">📈 Тарифи</button>
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
        // 🚀 1. Початок роботи
        {cat: "start", q: "Огляд робочого простору (Dashboard).", a: "Дашборд — це ваш головний екран. Він у реальному часі відображає фінансові метрики, воронку записів, завантаженість майстрів та автоматично сегментує клієнтів на VIP, постійних та нових на основі їх LTV."},
        {cat: "start", q: "Як підключити першого співробітника?", a: "Відкрийте 'Конфігурація' -> 'Експерти' та натисніть 'Додати'. Вкажіть ПІБ співробітника, оберіть посаду та прив'яжіть послуги. Згодом ви зможете згенерувати йому унікальний логін для входу в систему."},
        {cat: "start", q: "Як змінити свій пароль?", a: "Власник бізнесу змінює пароль у розділі 'Конфігурація', а майстер — безпосередньо у власному профілі після авторизації. При втраті доступу безпечне відновлення здійснюється лише через супер-адміністратора."},
        {cat: "start", q: "Як створити філію?", a: "У панелі власника перейдіть до 'Конфігурація' -> 'Філії'. Введіть назву нової локації, місто, адресу та створіть логін/пароль для керівника. Філія функціонуватиме як повністю ізольований суб-акаунт."},
        {cat: "start", q: "Як перемикатися між філіями?", a: "У списку філій поруч із кожною точкою є кнопка 'Увійти'. Натиснувши її, система миттєво перенаправить вас у панель керування обраної локації без необхідності повторної авторизації."},
        {cat: "start", q: "Як налаштувати графік роботи?", a: "Введіть графік у розділі 'ШІ Асистент' (наприклад: Пн-Пт 09:00-20:00). Бот автоматично скануватиме ці години і ніколи не пропонуватиме клієнтам час поза межами робочого розкладу."},
        {cat: "start", q: "Де знайти віджет для сайту?", a: "Посилання на публічний віджет доступне на Дашборді (кнопка 'Віджет'). Ви можете інтегрувати його на свій сайт (через iframe) або додати в шапку профілю Instagram (Linktree)."},
        {cat: "start", q: "Які є ролі користувачів?", a: "Система підтримує чітке розмежування прав: Власник (повний фінансовий контроль), Маркетолог (ШІ та аналітика), Адміністратор (робота з записами) та Майстер (бачить виключно свій розклад)."},
        {cat: "start", q: "Як відновити забутий пароль?", a: "Для максимального захисту від злому функція самостійного відновлення через email вимкнена. Зверніться до підтримки (Telegram), щоб супер-адмін згенерував вам новий тимчасовий ключ."},
        {cat: "start", q: "Як додати нову послугу в прайс?", a: "В 'Конфігурації' оберіть вкладку 'Послуги'. Вкажіть назву послуги, її фіксовану вартість у гривнях та тривалість виконання у хвилинах. Ці дані миттєво стануть доступними для ШІ-асистента."},
        {cat: "start", q: "Як видалити послугу чи майстра?", a: "Натисніть іконку кошика поруч із відповідним записом у списку. Зверніть увагу: ця дія не видалить історичні записи в календарі, пов'язані з цим майстром або послугою."},
        {cat: "start", q: "Чи можу я змінити назву бізнесу?", a: "Назва фіксується при реєстрації для юридичної звітності та формування договорів. Для зміни фактичної назви бренду зверніться до вашого персонального менеджера."},
        {cat: "start", q: "Що робити після реєстрації?", a: "Покроковий старт: 1) Додайте прайс-лист. 2) Створіть профілі майстрів. 3) Вкажіть графік роботи та налаштуйте Prompt для ШІ. 4) Підключіть токен Telegram для тестування бота."},
        {cat: "start", q: "Як додати логотип бренду?", a: "Система автоматично створює стильний аватар з першої літери вашої назви. Функція завантаження графічного логотипу для кастомізації чеків зараз знаходиться на стадії тестування."},
        {cat: "start", q: "Де знайти свій договір?", a: "Ваші підписані документи надійно шифруються та зберігаються на хмарному сервері. Для отримання їх цифрової копії надішліть офіційний запит до служби технічної підтримки."},
        {cat: "start", q: "Чи є мобільний додаток?", a: "SafeOrbit розроблено як PWA-додаток. Відкрийте CRM у мобільному браузері, натисніть 'Поділитися' -> 'Додати на головний екран', і ви отримаєте повноцінний застосунок на телефоні."},
        {cat: "start", q: "Як змінити часовий пояс?", a: "Серверна частина оптимізована під офіційний час Києва (Europe/Kyiv). Для міжнародних філій синхронізація часу налаштовується індивідуально через звернення до техпідтримки."},
        {cat: "start", q: "Як очистити всі дані?", a: "Для безпечного обнулення тестових записів і клієнтської бази перед офіційним запуском зверніться до адміністратора. Налаштування ШІ та токени при цьому будуть повністю збережені."},
        {cat: "start", q: "Як імпортувати базу клієнтів?", a: "Підготуйте свою поточну базу клієнтів у форматі CSV або таблиці Excel. Наша команда технічної підтримки безкоштовно та коректно імпортує її у ваш новий акаунт."},
        {cat: "start", q: "Що таке 'Швидкий старт'?", a: "Це преміум-послуга онбордингу 'під ключ', де наші інженери самостійно створюють ваш прайс, пишуть ідеальний Prompt для ШІ та підключають усі необхідні API-інтеграції."},

        // 🤖 2. Налаштування ШІ
        {cat: "ai", q: "Як активувати ШІ-асистента?", a: "В розділі 'AI Асистенти' вставте токен бота (напр. від Telegram) і збережіть зміни. Нейромережа одразу отримає доступ до розкладу і почне обробляти повідомлення клієнтів."},
        {cat: "ai", q: "Що таке 'Конструктор Особистості'?", a: "Це візуальний інструмент для швидкого створення системного Prompt'у. Вибираючи тон, мову та емодзі, ви формуєте унікальний стиль поведінки вашого бота без навичок програмування."},
        {cat: "ai", q: "Як навчити ШІ моєму прайсу?", a: "Бот не потребує ручного навчання прайсу. Він має інтелектуальний доступ до бази даних ('Послуги' та 'Склад') і підтягує актуальні ціни безпосередньо в момент діалогу."},
        {cat: "ai", q: "Як ШІ пропонує вільні вікна?", a: "Модель аналізує робочий графік, перевіряє тривалість запитуваної послуги та сканує календар. Після цього вона формує список з 3-4 реально вільних слотів для клієнта."},
        {cat: "ai", q: "Як змінити модель ШІ?", a: "У налаштуваннях ШІ виберіть модель з випадаючого списку. Рекомендуємо Llama 3.3 70B для складних інтелектуальних діалогів або Llama 8B для миттєвих відповідей."},
        {cat: "ai", q: "Що таке 'Температура' ШІ?", a: "Це індекс креативності моделі (від 0.0 до 1.0). Для точної технічної підтримки встановіть 0.3. Якщо потрібні розгорнуті і творчі продажі — підвищіть до 0.7."},
        {cat: "ai", q: "Чи розуміє ШІ голосові повідомлення?", a: "Наразі підтримується лише текстовий ввід. Модуль комп'ютерного слуху (STT) на базі Whisper для розпізнавання аудіо знаходиться в активній стадії розробки."},
        {cat: "ai", q: "Як працює допродаж (Upsell)?", a: "Увімкніть стратегію допродажу в Конструкторі. Бот аналізуватиме контекст і проактивно пропонуватиме логічні доповнення (наприклад, маску після фарбування)."},
        {cat: "ai", q: "Як обмежити довжину відповідей?", a: "Встановіть у Конструкторі опцію 'Лаконічно' або зменшіть параметр 'Макс. токенів' до 150. Бот змінить парадигму і відповідатиме короткими 1-2 реченнями."},
        {cat: "ai", q: "Що робити при системних помилках ШІ?", a: "Відкрийте 'Системну інструкцію' і допишіть жорстке правило. Наприклад: 'ЗАБОРОНЕНО записувати до 10:00'. ШІ негайно врахує цей контекст у нових діалогах."},
        {cat: "ai", q: "Як бот реагує на 'поклич людину'?", a: "ШІ має базовий тригер на слова 'адмін', 'людина', 'оператор'. Він миттєво припиняє генерацію відповідей і надсилає Push-сповіщення живому менеджеру."},
        {cat: "ai", q: "Як ШІ дізнається про товари магазину?", a: "Бот читає вашу вкладку 'Склад'. Коли клієнт запитує наявність, ШІ перевіряє залишки, запитує потрібний колір/розмір і оформлює замовлення на доставку."},
        {cat: "ai", q: "Чи може ШІ скасувати запис?", a: "Так, функціонал підтримує скасування. Якщо ідентифікований клієнт просить відмінити візит, бот знаходить його запис, анулює його і звільняє час у календарі."},
        {cat: "ai", q: "Як ШІ працює зі знижками?", a: "Якщо у CRM профілі клієнта зафіксовано знижку (напр. 15%), бот автоматично перераховує фінальну ціну послуги та наголошує клієнту на його персональній вигоді."},
        {cat: "ai", q: "Чи вміє бот жартувати?", a: "Абсолютно. Якщо в Конструкторі обрати 'Грайливий' тон, модель почне підтримувати неформальну бесіду, використовувати гумор та велику кількість емодзі."},
        {cat: "ai", q: "Скільки мов підтримує ШІ?", a: "Базово прописані українська, англійська та польська мови. У режимі 'Мультимовний' нейромережа автоматично розпізнає мову клієнта і відповідає нею ж."},
        {cat: "ai", q: "Як бот звертається до клієнтів?", a: "Ви можете жорстко задати формат звертання. Оберіть шанобливе 'На Ви' для преміум сегменту, або дружнє 'На Ти' для сучасних молодіжних брендів."},
        {cat: "ai", q: "Чи можу я сам написати Prompt?", a: "Так, ви можете повністю ігнорувати Конструктор. Напишіть власний детальний Prompt у текстовому полі 'Системна інструкція', впровадивши будь-які специфічні алгоритми."},
        {cat: "ai", q: "Що таке 'Макс. токенів'?", a: "Це обмеження на фізичний об'єм згенерованого тексту. Значення 1024 токенів дозволяє боту давати розгорнуті прайси без обривання тексту на половині слова."},
        {cat: "ai", q: "Як ШІ розпізнає послугу з опису?", a: "Llama 3.3 використовує глибокий семантичний аналіз тексту. Якщо клієнт просить 'зробити волосся світлішим', модель чітко зрозуміє, що йдеться про 'Фарбування'."},
        {cat: "ai", q: "Чи можна вимкнути ШІ на ніч?", a: "Бот працює 24/7, конвертуючи ліди вночі. Але ви можете додати в Prompt інструкцію: повідомляти, що заклад зачинено, і пропонувати час на ранок."},

        // 🔌 3. Інтеграції з CRM
        {cat: "integrations", q: "Altegio через API.", a: "Введіть токен та ID компанії в налаштуваннях Altegio. Після збереження ШІ почне сканувати вільні вікна та майстрів безпосередньо з вашої зовнішньої CRM."},
        {cat: "integrations", q: "BeautyPro синхронізація.", a: "Вкажіть токен та ID локації BeautyPro. Ця інтеграція дозволяє миттєво дублювати всі нові AI-записи у ваш основний розклад BeautyPro."},
        {cat: "integrations", q: "Інтеграція Cleverbox.", a: "Введіть API URL та токен доступу Cleverbox. Ваші гарячі ліди з месенджерів автоматично потраплятимуть до клієнтської бази Cleverbox."},
        {cat: "integrations", q: "Підключення Integrica.", a: "Збережіть токен та ID локації в каталозі інтеграцій. Синхронізація контактних даних та деталей запису відбувається в режимі реального часу."},
        {cat: "integrations", q: "LuckyFit.", a: "Потрібен лише API токен. Ця оптимізована інтеграція ідеально підходить для фітнес-студій, передаючи інформацію про бронювання групових тренувань."},
        {cat: "integrations", q: "uSpacy.", a: "Введіть Token та Workspace ID. Модуль автоматично передає створені ботом ліди безпосередньо у воронку продажів (Kanban) uSpacy для менеджерів."},
        {cat: "integrations", q: "Dikidi.", a: "Розробка офіційного модуля синхронізації з Dikidi знаходиться на фінальній стадії. Слідкуйте за технічними оновленнями системи в Telegram-каналі."},
        {cat: "integrations", q: "Перевірка інтеграції.", a: "Перейдіть у 'Журнал подій'. У разі успішної відправки даних у сторонню CRM там гарантовано з'явиться зелений лог із відповідним підтвердженням."},
        {cat: "integrations", q: "Запис не з'явився в CRM.", a: "Перевірте, чи увімкнено перемикач 'CRM: Увімк' у панелі супер-адміністратора, і чи не містить ваш токен зайвих прихованих пробілів."},
        {cat: "integrations", q: "Дві CRM одночасно?", a: "Так, архітектура підтримує мультиканальність. Ви можете паралельно відправляти ліди в uSpacy та одночасно фіксувати жорсткі записи в Altegio."},
        {cat: "integrations", q: "Імпорт бази з CRM.", a: "Масова викачка бази поки не підтримується. Клієнти завантажуються поступово: при кожному новому зверненні його картка синхронізується з основною CRM."},
        {cat: "integrations", q: "WINS.", a: "Збережіть токен та Branch ID у налаштуваннях WINS. Підтримується надійна двостороння передача статусів запису між системами."},
        {cat: "integrations", q: "Doctor Eleks.", a: "Введіть Token та Clinic ID. Ця інтеграція адаптована спеціально для медичних центрів і суворо враховує специфіку розкладу лікарів."},
        {cat: "integrations", q: "Appointer.", a: "Введіть токен та Location ID у відповідне поле. Бот зможе бронювати час, орієнтуючись на реальну зайнятість кабінетів в системі Appointer."},
        {cat: "integrations", q: "EasyWeek.", a: "Синхронізація підтримується повністю. Введіть API ключ, і система автоматично зв'яже послуги за їхніми назвами та ідентифікаторами."},
        {cat: "integrations", q: "Trendis.", a: "Введіть токен та Location ID для передачі записів. Рішення чудово підходить для сучасних салонів краси, що використовують платформу Trendis."},
        {cat: "integrations", q: "MioPane.", a: "Для підключення MioPane потрібні токен та ID локації. Бот автоматично отримуватиме актуальні дані про доступність майстрів з розкладу."},
        {cat: "integrations", q: "Clinica Web.", a: "Інтеграція доступна для медичних закладів. Вона дозволяє повністю автоматизувати первинну реєстрацію пацієнтів через Telegram-бота."},
        {cat: "integrations", q: "Помилка 401 в логах.", a: "Статус 401 означає 'Unauthorized'. Ваш API-токен від сторонньої CRM застарів, введений з помилкою або був заблокований на їхньому боці."},
        {cat: "integrations", q: "Затримка синхронізації.", a: "Наші сервери відправляють дані миттєво (через Webhooks). Затримка у 3-5 секунд можлива лише при перевантаженні серверів сторонньої CRM."},
        {cat: "integrations", q: "Чи синхронізуються ціни?", a: "Так, SafeOrbit передає фінальну вартість (з урахуванням ШІ-допродажів та знижок), щоб у вашій CRM завжди відображався коректний чистий дохід."},

        // 📱 4. Месенджери
        {cat: "messengers", q: "Instagram Direct.", a: "Підключення вимагає Access Token від Meta. Оскільки налаштування через Facebook Developer Console є надскладним, наші інженери роблять це під ключ."},
        {cat: "messengers", q: "Telegram-бот.", a: "Створіть нового бота у @BotFather, скопіюйте HTTP API Token і вставте його у налаштування SafeOrbit. AI-бот почне працювати миттєво."},
        {cat: "messengers", q: "WhatsApp Business API.", a: "Підключення можливе виключно через офіційних провайдерів Meta (BSP). Процес бізнес-реєстрації номера займає близько 3 днів."},
        {cat: "messengers", q: "Viber Chatbots.", a: "Створіть бота у Viber Partner Portal, скопіюйте унікальний токен та введіть його в системі. Підтримуються всі діалогові функції ШІ."},
        {cat: "messengers", q: "Facebook Messenger.", a: "Модуль налаштовується паралельно з Instagram Direct, оскільки використовує єдину хмарну інфраструктуру Meta Webhooks для відправки повідомлень."},
        {cat: "messengers", q: "Як відповісти вручну?", a: "Відкрийте вкладку 'Комунікації', знайдіть потрібний діалог і введіть текст. ШІ автоматично призупиниться, щоб не перебивати вас під час розмови."},
        {cat: "messengers", q: "Чи бачить ШІ старі переписки?", a: "Так, бот автоматично завантажує в пам'ять контекст останніх 30 повідомлень діалогу. Це дозволяє йому не ставити клієнту повторних питань."},
        {cat: "messengers", q: "Сповіщення в Telegram.", a: "Вкажіть свій особистий Chat ID (або ID групи з мінусом попереду) у налаштуваннях, щоб отримувати миттєві алерти про нові успішні записи."},
        {cat: "messengers", q: "Ідентифікація клієнтів.", a: "Система безпомилково розпізнає клієнта за унікальним Chat ID. Якщо клієнт надає свій телефон, його профіль автоматично об'єднується з базою."},
        {cat: "messengers", q: "Захист від спаму.", a: "ШІ має вбудований Rate Limiting. Якщо користувач надсилає десятки повідомлень за секунду, бот ігнорує його для захисту ваших серверних ресурсів."},
        {cat: "messengers", q: "Надсилання фото.", a: "Наразі інтерфейс та ШІ обробляють виключно текстові запити. Підтримка комп'ютерного зору (Computer Vision) для фото запланована на майбутнє."},
        {cat: "messengers", q: "Віджет на сайт.", a: "Натисніть кнопку 'Віджет', щоб згенерувати публічне посилання. Ви можете додати його на свій корпоративний сайт або в Linktree Instagram."},
        {cat: "messengers", q: "Зміна імені бота.", a: "Ім'я, опис та аватар бота змінюються не в нашій CRM, а безпосередньо в налаштуваннях месенджера (наприклад, через команди у @BotFather)."},
        {cat: "messengers", q: "Як відключити месенджер?", a: "Щоб призупинити роботу ШІ-бота в конкретному каналі, просто зітріть його токен у налаштуваннях інтеграцій і натисніть кнопку збереження."},
        {cat: "messengers", q: "Чи є ліміт повідомлень?", a: "Для користувачів PRO-тарифу будь-які ліміти відсутні. У базовому тарифі діє політика чесного використання для запобігання перевантажень API."},
        {cat: "messengers", q: "Блокування клієнта.", a: "Функція повноцінного чорного списку знаходиться в розробці. Наразі ви можете просто ігнорувати небажані діалоги у вкладці 'Комунікації'."},
        {cat: "messengers", q: "Групові чати Telegram.", a: "Нейромережа оптимізована виключно для особистих (Direct) повідомлень. Додавання бота в групи не підтримується задля збереження конфіденційності."},
        {cat: "messengers", q: "Надсилання локації.", a: "Бот може надіслати текстом вашу точну адресу та пояснити, як дістатися. Відправка живої геолокації картою наразі не підтримується платформою."},
        {cat: "messengers", q: "Автовідповідач.", a: "Бот повністю замінює стандартний автовідповідач. Вночі він повноцінно спілкується, відповідає на питання і записує клієнтів на вільний ранковий час."},
        {cat: "messengers", q: "Історія чатів.", a: "Всі діалоги надійно шифруються і безстроково зберігаються у базі даних. Ви можете будь-коли переглянути їх та проаналізувати у вкладці 'Комунікації'."},
        {cat: "messengers", q: "Скільки ботів можна додати?", a: "За одним бізнес-акаунтом можна закріпити строго по одному боту для кожного месенджера (один Telegram, один Viber тощо)."},

        // 📞 5. Голосовий ШІ
        {cat: "voice", q: "Як активувати голосовий ШІ?", a: "Голосовий ШІ доступний виключно в PRO-тарифі. Для його активації потрібна персональна консультація з інженером для налаштування SIP-транку (Vapi/Retell)."},
        {cat: "voice", q: "Binotel.", a: "Введіть API ключ та секрет з кабінету Binotel. Це дозволить безперебійно маршрутизувати вхідні дзвінки з вашої АТС безпосередньо на нейромережу."},
        {cat: "voice", q: "Phonet.", a: "Вкажіть домен, ключ та пароль Phonet. Інтеграція підтримує передачу контексту дзвінка та автоматичне збереження аудіозапису розмови в нашій CRM."},
        {cat: "voice", q: "Ringostat.", a: "Введіть Auth Token для відстеження дзвінків. Ringostat дозволяє додатково аналізувати маркетингові джерела (Call Tracking), з яких прийшов ваш клієнт."},
        {cat: "voice", q: "Чи може ШІ сам записувати?", a: "Так, голосовий асистент має миттєвий доступ до вашого календаря. Під час розмови він знаходить вільне вікно і одразу створює підтверджений запис."},
        {cat: "voice", q: "Переведення дзвінка на людину.", a: "У налаштуваннях вкажіть 'transfer_phone_number'. Якщо клієнт ставить нестандартне питання, бот безшовно переведе дзвінок на ваш мобільний."},
        {cat: "voice", q: "Записи розмов.", a: "Оригінальні аудіозаписи всіх розмов з ШІ, а також їх повна текстова транскрипція, автоматично зберігатимуться в картці клієнта для контролю якості."},
        {cat: "voice", q: "Вибір голосу.", a: "Ви можете обрати голос (тембр, стать, акцент) на стороні провайдерів ElevenLabs або OpenAI. Наші інженери допоможуть підібрати ідеальне звучання."},
        {cat: "voice", q: "SMS-нагадування.", a: "Для автоматичної відправки SMS-нагадувань підключіть провайдера TurboSMS. У розкладі з'явиться можливість надсилати повідомлення в один клік."},
        {cat: "voice", q: "Twilio.", a: "Twilio є міжнародним провайдером. Введіть Account SID та Auth Token для відправки SMS за кордон (ідеально підходить для філій у Європі чи США)."},
        {cat: "voice", q: "eSputnik.", a: "Інтеграція з eSputnik підтримується для створення масових тригерних розсилок. Дані з нашої CRM автоматично оновлюють сегменти у вашому eSputnik-акаунті."},
        {cat: "voice", q: "Швидкість відповіді голосом.", a: "Завдяки використанню надшвидких процесорів Groq затримка між реплікою клієнта та відповіддю бота становить менше 800 мілісекунд (імітація живої людини)."},
        {cat: "voice", q: "Синтез мовлення (TTS).", a: "Генерація голосу (Text-to-Speech) відбувається через найсучасніші нейромережі, які здатні робити паузи, зітхати та інтонувати текст природно."},
        {cat: "voice", q: "Розпізнавання (STT).", a: "Модуль розпізнавання (Speech-to-Text) відмінно розуміє українську мову, суржик, слова-паразити та ігнорує фоновий шум на вулиці."},
        {cat: "voice", q: "Вхідні та вихідні?", a: "Бот здатний як приймати вхідні дзвінки від лідів (замінюючи адміністратора), так і робити вихідні обдзвони бази для збору NPS-оцінок."},
        {cat: "voice", q: "Автовідповідач клієнта.", a: "Голосовий ШІ автоматично розпізнає автовідповідач (Voicemail) на стороні клієнта і одразу кладе слухавку, економлячи ваші кошти."},
        {cat: "voice", q: "Музика на фоні.", a: "Для збереження мінімальної затримки відповіді та зменшення навантаження на канал, фонова музика під час розмови з ботом наразі не використовується."},
        {cat: "voice", q: "Чи потрібна SIP-телефонія?", a: "Так, для роботи голосового бота обов'язково потрібна існуюча хмарна SIP-телефонія (Binotel, Phonet), до якої ми підключаємо нейромережу."},
        {cat: "voice", q: "Номер відправника SMS.", a: "Для відправки SMS з назвою вашого бренду (замість невідомого номера) вкажіть офіційно зареєстрований альфа-іменник (Sender ID) у налаштуваннях."},
        {cat: "voice", q: "Ціна за хвилину.", a: "Послуги голосового ШІ не тарифікуються нами. Ви сплачуєте виключно своєму провайдеру телефонії за хвилини розмови згідно з їхніми тарифами."},
        {cat: "voice", q: "Переадресація при зайнятості.", a: "Якщо ваша основна лінія зайнята живими менеджерами, система може переадресувати вхідний дзвінок на ШІ-асистента, щоб не втратити ліда."},
        
        // 💰 6. Оплати
        {cat: "billing", q: "Monobank API.", a: "Введіть X-Token (генерується в кабінеті ФОП). Це дозволить CRM автоматично відстежувати надходження коштів та змінювати статуси замовлень на 'Оплачено'."},
        {cat: "billing", q: "Fondy.", a: "Для підключення еквайрингу Fondy введіть Merchant ID та Secret Key. Завдяки цьому ви зможете приймати оплати картками (Apple Pay/Google Pay) онлайн."},
        {cat: "billing", q: "WayForPay.", a: "Введіть Merchant Account та Secret Key. WayForPay є популярним українським шлюзом з низькими комісіями для безпечного прийому онлайн-платежів."},
        {cat: "billing", q: "LiqPay.", a: "Інтеграція з LiqPay вимагає введення Public Key та Private Key з кабінету ПриватБанку. Ідеально підходить для бізнесів, що обслуговуються в ПБ."},
        {cat: "billing", q: "Stripe.", a: "Введіть Secret Key для прийому міжнародних платежів. Stripe повністю підтримує розрахунки в USD, EUR та інших іноземних валютах."},
        {cat: "billing", q: "Фіскальний чек.", a: "Відкрийте деталі запису в календарі та натисніть кнопку 'Друк' (іконка принтера). Система миттєво згенерує стилізований PDF-чек для термопринтера."},
        {cat: "billing", q: "Доходи в статистиці.", a: "На дашборді автоматично сумується вартість виключно тих записів, що мають статус 'Виконано'. Скасовані або очікувані візити дохід не формують."},
        {cat: "billing", q: "Як ШІ обробляє ціни?", a: "ШІ-бот зчитує ціни безпосередньо з вашої вкладки 'Послуги'. Якщо ви оновили прайс, бот почне використовувати нові ціни вже через секунду."},
        {cat: "billing", q: "Знижки клієнтів.", a: "У профілі клієнта можна встановити персональну знижку у відсотках. При записі ШІ застосує її до ціни і приємно наголосить на цьому клієнту."},
        {cat: "billing", q: "Оплата підписки SafeOrbit.", a: "Оплата за CRM здійснюється переказом за реквізитами IBAN ФОП або через безпечне платіжне посилання, яке щомісяця генерує менеджер."},
        {cat: "billing", q: "Зміна валюти.", a: "Базово вся система працює з гривнею (UAH). Підтримка інших валют та автоматична конвертація доступні виключно на PRO-тарифі."},
        {cat: "billing", q: "Повернення коштів клієнту.", a: "Повернення коштів (Refund) наразі не автоматизовано в CRM. Вам потрібно ініціювати цю процедуру вручну в кабінеті вашого платіжного шлюзу."},
        {cat: "billing", q: "Генерація посилань.", a: "Функція автоматичної генерації унікального посилання на оплату безпосередньо в чаті знаходиться на стадії тестування і з'явиться в наступному патчі."},
        {cat: "billing", q: "Передоплата.", a: "Ви можете налаштувати обов'язкову часткову передоплату. ШІ надішле клієнту реквізити та чекатиме підтвердження (скріншоту) перед фіксацією часу."},
        {cat: "billing", q: "Комісія еквайрингу.", a: "SafeOrbit не стягує жодних прихованих комісій з ваших транзакцій. Ви сплачуєте виключно стандартну комісію вашого банку (зазвичай 1.2-1.5%)."},
        {cat: "billing", q: "Звіт по фінансах.", a: "У розділі аналітики ви можете в один клік експортувати список усіх записів разом з їхньою фінальною вартістю у CSV-файл для подальшого аналізу."},
        {cat: "billing", q: "Собівартість товару.", a: "Додаючи товар на склад, обов'язково вказуйте його собівартість (Unit Cost). Це дозволить системі автоматично вираховувати ваш чистий прибуток."},
        {cat: "billing", q: "Мультивалютність.", a: "Мультивалютність підтримується при підключенні Stripe. Бот може називати ціни у валюті клієнта, спираючись на локацію його телефонного номера."},
        {cat: "billing", q: "Додавання чайових.", a: "Клієнт може залишити безготівкові чайові майстру на етапі онлайн-оплати візиту через Fondy або WayForPay (якщо ця функція увімкнена)."},
        {cat: "billing", q: "Статуси оплат.", a: "При інтеграції з Monobank або Fondy статус запису автоматично зміниться з 'Очікується' на 'Оплачено', щойно гроші надійдуть на ваш рахунок."},
        {cat: "billing", q: "Реквізити на чеку.", a: "На товарному чеку автоматично друкуються назва вашого бізнесу, юридична адреса, час візиту, перелік наданих послуг та фінальна сума."},

        // 📊 7. Аналітика
        {cat: "analytics", q: "Що на Дашборді?", a: "Дашборд відображає глобальну картину: кількість візитів за сьогодні/місяць, сумарний дохід, кругові діаграми послуг та рейтинг топ-клієнтів."},
        {cat: "analytics", q: "Джерела записів.", a: "Цей графік наочно показує відсоток лідів, яких успішно закрив ШІ-асистент, у порівнянні із записами, які адміністратор додав вручну."},
        {cat: "analytics", q: "Топ гостей.", a: "Алгоритм системи автоматично визначає VIP-клієнтів (за найбільшим LTV) і виводить їх у топ списку для вашої особливої уваги."},
        {cat: "analytics", q: "Завантаженість майстрів.", a: "У розділі календаря ви можете застосувати фільтр по кожному майстру, щоб побачити щільність його розкладу та оцінити ефективність."},
        {cat: "analytics", q: "Журнал подій.", a: "У вкладці 'Журнал подій' ведеться суворий аудит: фіксуються зміни налаштувань ШІ, створення записів та помилки інтеграцій."},
        {cat: "analytics", q: "Експорт бази.", a: "Ви можете в один клік скопіювати всю таблицю клієнтів з вкладки 'База клієнтів'. Формування чистого CSV-файлу буде додано пізніше."},
        {cat: "analytics", q: "ШІ-аналітик.", a: "Натиснувши на іконку робота внизу, ви можете спитати: 'Скільки записів на завтра?'. ШІ проаналізує базу і видасть точну текстову відповідь."},
        {cat: "analytics", q: "Історія візитів.", a: "Уся історія візитів, суми чеків та скасовані записи назавжди зберігаються у розширеній цифровій картці кожного клієнта."},
        {cat: "analytics", q: "Статистика складу.", a: "На вкладці 'Склад' ви контролюєте актуальні залишки товарів. ШІ враховує цю кількість при обробці запитів від покупців."},
        {cat: "analytics", q: "Скасовані записи.", a: "Червоний індикатор на дашборді одразу сигналізує про скасовані візити. Аналізуйте ці дані, щоб вчасно реагувати на відтік клієнтів."},
        {cat: "analytics", q: "Конверсія бота.", a: "Цей складний показник вираховується автоматично шляхом ділення кількості унікальних чатів на кількість реально створених записів."},
        {cat: "analytics", q: "RFM-аналіз.", a: "Фоновий процес автоматично ділить вашу базу на 'Сплячих', 'Нових' та 'VIP' клієнтів залежно від давності та частоти їхніх покупок."},
        {cat: "analytics", q: "Середній чек.", a: "Хочете дізнатися середній чек? Просто запитайте про це вбудованого ШІ-асистента. Він миттєво підрахує суму за обраний період."},
        {cat: "analytics", q: "Фільтр по датах.", a: "Гнучка навігація місяцями та тижнями доступна у вкладці 'Календар'. Ви можете легко планувати роботу на кілька місяців вперед."},
        {cat: "analytics", q: "Кількість нових лідів.", a: "Кожен унікальний контакт, що написав боту (навіть без запису), назавжди зберігається у вашу базу для подальшого ремаркетингу."},
        {cat: "analytics", q: "Продажі товарів.", a: "Якщо у вас Retail-бізнес, замовлення з адресою доставки будуть візуально виділені спеціальною іконкою 'Вантажівка' у загальному списку."},
        {cat: "analytics", q: "Звіт по годинах.", a: "Побудова візуальної теплової карти (Heatmap) найбільш завантажених годин вашого закладу знаходиться у стадії фінальної розробки."},
        {cat: "analytics", q: "Графік доходів.", a: "Лінійний графік на дашборді демонструє динаміку зростання 'Цінності клієнтів' (LTV) протягом поточного фінансового місяця."},
        {cat: "analytics", q: "Аналітика розсилок.", a: "Після відправки глобальної розсилки система збирає базову статистику успішно доставлених повідомлень по базі."},
        {cat: "analytics", q: "NPS оцінки.", a: "Система здатна автоматично збирати оцінки від 1 до 5 від клієнтів після візиту, формуючи середній бал якості обслуговування."},
        {cat: "analytics", q: "Продуктивність ШІ.", a: "За даними нашої аналітики, бот SafeOrbit бере на себе 80% рутини, заощаджуючи в середньому 40-60 годин робочого часу адміністратора."},

        // 🔒 8. Безпека
        {cat: "security", q: "Конфіденційність.", a: "Ваша база клієнтів надійно шифрується (AES-256) і зберігається на повністю ізольованих інстансах. Ми гарантуємо непередачу даних третім особам."},
        {cat: "security", q: "Доступ ШІ.", a: "Нейромережа має доступ ЛИШЕ до вашого графіка та прайсу. На рівні ядра ШІ суворо заборонено читати або розголошувати чужі персональні дані."},
        {cat: "security", q: "NDA.", a: "Підписання Угоди про нерозголошення (NDA) є обов'язковою процедурою перед активацією акаунту. Вона юридично захищає вашу комерційну таємницю."},
        {cat: "security", q: "Резервне копіювання.", a: "Ми здійснюємо автоматичне створення знімків бази даних (Backups) щодня о 03:00. Ваші дані у повній безпеці від випадкової втрати."},
        {cat: "security", q: "Двофакторна (2FA).", a: "Функція входу через код з SMS або Google Authenticator (2FA) наразі тестується і буде розгорнута в найближчому пакеті оновлень безпеки."},
        {cat: "security", q: "Доступ майстрів.", a: "Майстер авторизується під власним логіном і бачить виключно записи, закріплені за ним. Модулі фінансів, налаштувань та бази клієнтів від нього приховані."},
        {cat: "security", q: "GDPR.", a: "Архітектура SafeOrbit повністю відповідає європейським регламентам приватності (GDPR) щодо безпечного збору та зберігання персональних даних."},
        {cat: "security", q: "Видалення акаунту.", a: "Для повного видалення вашого бізнес-профілю з усіх серверів зверніться із запитом до служби підтримки. Дані стираються безповоротно."},
        {cat: "security", q: "Платіжні дані.", a: "Ми ніколи не зберігаємо номери банківських карток клієнтів. Усі фінансові транзакції проходять через захищені шлюзи офіційних еквайєрів."},
        {cat: "security", q: "Логи сесій.", a: "Усі критичні входи в панель керування фіксуються із записом IP-адреси. Ви можете запросити детальний звіт про сесії авторизації у підтримки."},
        {cat: "security", q: "SSL сертифікат.", a: "З'єднання між вашим браузером та нашими серверами надійно захищене військовим протоколом HTTPS з 2048-бітним ключем шифрування."},
        {cat: "security", q: "Розмежування прав.", a: "Система має жорстку ієрархію доступу: Власник (всі права) > Маркетолог > Адміністратор > Майстер (лише читання свого розкладу)."},
        {cat: "security", q: "Захист від DDoS.", a: "Вся мережева інфраструктура SafeOrbit прихована за потужними екранами захисту Cloudflare, що гарантує 99.9% аптайму під час DDoS-атак."},
        {cat: "security", q: "Prompt Injection.", a: "Бот має багаторівневий системний захист від хакерських спроб 'зламати' інструкції (Prompt Injection) або змусити бота ігнорувати правила."},
        {cat: "security", q: "Ізоляція даних.", a: "Архітектура (Multi-tenant) побудована так, що кожен бізнес працює у власному ізольованому кластері. Витік даних до інших клієнтів виключений."},
        {cat: "security", q: "Аудит безпеки.", a: "Наш код та серверна інфраструктура щоквартально проходять незалежний аудит безпеки (Penetration Testing) для виявлення та закриття вразливостей."},
        {cat: "security", q: "Відновлення пароля.", a: "З метою захисту від соціальної інженерії зміна втраченого пароля можлива ВИКЛЮЧНО через ручну верифікацію супер-адміністратором системи."},
        {cat: "security", q: "Зміна власника.", a: "Передача прав власності на акаунт іншій особі можлива лише після підписання офіційної електронної заяви обома сторонами процесу."},
        {cat: "security", q: "Експорт бази.", a: "Кнопка масового експорту клієнтської бази доступна виключно користувачам з роллю 'Власник', щоб уникнути крадіжки бази менеджерами."},
        {cat: "security", q: "Вимоги до пароля.", a: "Система приймає паролі довжиною не менше 8 символів. Паролі хешуються складним криптографічним алгоритмом Bcrypt."},
        {cat: "security", q: "Доступ підтримки.", a: "Наші інженери можуть зайти у ваш акаунт для виправлення помилок ТІЛЬКИ після вашого прямого письмового дозволу в офіційному чаті підтримки."},

        // 🆘 9. Вирішення проблем
        {cat: "troubleshooting", q: "ШІ не відповідає.", a: "Перевірте дві речі: чи коректно вставлений токен бота (без зайвих пробілів) та чи увімкнений перемикач 'ШІ Асистент' у панелі супер-адміністратора."},
        {cat: "troubleshooting", q: "Немає сповіщень Telegram.", a: "Переконайтеся, що ви поставили галочку біля 'Telegram Chat ID для сповіщень'. Якщо це груповий чат, його ID обов'язково має починатися з мінуса (-100...)."},
        {cat: "troubleshooting", q: "ШІ змінив мову.", a: "Таке буває, коли клієнт починає писати англійською. Щоб виправити це, жорстко вкажіть 'Українська' у Конструкторі і збережіть новий Prompt."},
        {cat: "troubleshooting", q: "Помилка збереження.", a: "Скиньте кеш браузера комбінацією Ctrl+Shift+R (Cmd+Shift+R для Mac) та перевірте підключення до мережі. Якщо не допомогло — пишіть у підтримку."},
        {cat: "troubleshooting", q: "Помилка Altegio.", a: "Згенеруйте новий API-токен доступу у вашому кабінеті Altegio. Старий ключ міг бути анульований політикою безпеки сторонньої CRM."},
        {cat: "troubleshooting", q: "Віджет не працює.", a: "Переконайтеся, що ваш бізнес-акаунт не заблоковано за несплату. Заблоковані профілі втрачають доступ до генерації публічних посилань."},
        {cat: "troubleshooting", q: "Неправильні ціни.", a: "Бот не вигадує ціни, він бере їх із вкладки 'Послуги'. Оновіть там вартість, і бот миттєво почне використовувати оновлені дані в діалогах."},
        {cat: "troubleshooting", q: "Скидання налаштувань.", a: "Щоб повернути базові налаштування ШІ, просто повністю видаліть текст із поля 'Системна інструкція' і натисніть кнопку 'Зберегти'."},
        {cat: "troubleshooting", q: "Техпідтримка.", a: "Кнопка 'Написати в підтримку' вгорі сторінки переведе вас у наш офіційний Telegram-канал. Інженери відповідають протягом 15 хвилин у робочий час."},
        {cat: "troubleshooting", q: "Помилка 403.", a: "Ця помилка (Unauthorized) означає, що термін дії вашої сесії вичерпано. Вийдіть з акаунту через ліве меню і здійсніть вхід заново."},
        {cat: "troubleshooting", q: "Бот не пропонує вільний час.", a: "Перевірте, чи коректно заповнено поле 'Графік роботи'. Якщо воно порожнє або написано з помилкою, ШІ вважатиме, що заклад зачинено."},
        {cat: "troubleshooting", q: "Подвійні записи.", a: "Система має жорсткий захист від 'накладання' записів. Якщо виникає конфлікт, перевірте, чи правильно вказана тривалість (у хвилинах) для кожної послуги."},
        {cat: "troubleshooting", q: "Клієнт не отримує SMS.", a: "Авторизуйтесь у кабінеті вашого провайдера (напр. TurboSMS) і перевірте баланс. Відправка SMS не відбудеться при нульовому рахунку."},
        {cat: "troubleshooting", q: "Повільний ШІ.", a: "Модель 70B є надзвичайно розумною, але важкою. Для максимальної швидкості (до 1 сек) змініть модель на llama-3.1-8b у налаштуваннях."},
        {cat: "troubleshooting", q: "Пропали діалоги.", a: "Це тимчасовий візуальний збій рендеру сторінки. Оновіть сторінку браузера, і всі діалоги коректно підвантажаться із захищеної бази даних."},
        {cat: "troubleshooting", q: "Помилка 'Invalid API Key'.", a: "Цей лог означає, що один із ваших ключів (від CRM, месенджера або платіжного шлюзу) недійсний. Зверніться до підтримки для аудиту ключів."},
        {cat: "troubleshooting", q: "ШІ пропонує минулий час.", a: "Щоб бот не помилявся з часовими поясами, додайте в кінець Prompt'у фразу: 'Завжди перевіряй поточний час перед тим, як пропонувати слоти'."},
        {cat: "troubleshooting", q: "Як перевірити логи?", a: "Відкрийте вкладку 'Журнал подій'. Там висвітлюються всі приховані системні процеси, включаючи успішність синхронізації зі сторонніми сервісами."},
        {cat: "troubleshooting", q: "Бот повторюється.", a: "Якщо ШІ 'зациклився' і відповідає однією фразою, знизьте параметр 'Температура' до 0.3. Це зробить його відповіді більш жорсткими та детермінованими."},
        {cat: "troubleshooting", q: "Не завантажується фото в чат.", a: "Інтерфейс чату SafeOrbit наразі оптимізовано виключно для швидкого текстового обміну. Відправка зображень не передбачена ядром системи."},
        {cat: "troubleshooting", q: "Не працює кнопка.", a: "Деякі агресивні блокувальники реклами (на зразок uBlock Origin) можуть блокувати скрипти збереження. Додайте наш сайт у список виключень."},

        // 📈 10. Тарифи
        {cat: "pricing", q: "Базовий тариф.", a: "Вартість: 11 000 грн/міс. Включає: розумний текстовий ШІ, підключення Telegram/Instagram, 1 активну CRM інтеграцію та базовий модуль аналітики."},
        {cat: "pricing", q: "PRO тариф.", a: "Вартість: 53 000 грн (оплачується одноразово). Ви отримуєте довічну ліцензію, голосовий ШІ, підтримку всіх доступних месенджерів та пріоритетну кастомну розробку."},
        {cat: "pricing", q: "Тестовий період.", a: "Оскільки підключення ШІ вимагає дорогої ручної роботи інженерів та оренди серверних потужностей, ми не надаємо тестовий період. Натомість доступна персональна Zoom-демонстрація."},
        {cat: "pricing", q: "Плата за налаштування.", a: "Одноразовий платіж 9 000 грн (тільки у Базовому тарифі) покриває 10 годин роботи нашої команди: створення бази, написання промптів та тестування інтеграцій."},
        {cat: "pricing", q: "Перехід на PRO.", a: "Ви можете перейти з Базового на PRO в будь-який момент. Напишіть у підтримку, і ми врахуємо частину ваших попередніх абонентських платежів як знижку."},
        {cat: "pricing", q: "Знижки для мереж.", a: "Якщо ви розширюєтесь, кожна наступна філія підключається зі знижкою 50%. Наприклад, друга точка на базовому тарифі коштуватиме лише 5 500 грн/міс."},
        {cat: "pricing", q: "Способи оплати.", a: "Ви можете сплатити підписку за офіційними реквізитами IBAN на рахунок ФОП, або скористатися безпечним платіжним посиланням для оплати карткою через еквайринг."},
        {cat: "pricing", q: "Підтримка PRO.", a: "Для власників довічної PRO-ліцензії діє мінімальна абонплата 1 100 грн/міс. Вона покриває оренду серверів Llama, хмарні бекапи та оновлення системи безпеки."},
        {cat: "pricing", q: "Повернення коштів.", a: "Повернення коштів у повному обсязі гарантується протягом 14 днів після оплати, якщо наша система технічно не здатна виконувати заявлені функції для вашого бізнесу."},
        {cat: "pricing", q: "Кастомна розробка.", a: "Ексклюзивно для користувачів PRO-тарифу доступна розробка унікальних функцій. Наші інженери можуть створити будь-який модуль спеціально під специфіку ваших процесів."},
        {cat: "pricing", q: "Партнерська програма.", a: "Рекомендуйте SafeOrbit колегам і отримуйте пасивний дохід. Ми виплачуємо до 15% (Revenue Share) від усіх платежів залучених вами нових клієнтів."},
        {cat: "pricing", q: "Білінг цикл.", a: "Оплата за Базовий тариф списується рівно через 30 днів після фактичної дати вашої першої активації та успішного підключення бота."},
        {cat: "pricing", q: "Чи є комісія за запис?", a: "На відміну від агрегаторів, ми не стягуємо жодного відсотка чи комісії з ваших успішних замовлень. Ваш дохід залишається повністю вашим."},
        {cat: "pricing", q: "Скільки коштує голосовий ШІ?", a: "Доступ до модуля голосового ШІ включено у вартість PRO-тарифу. Ви додатково оплачуєте лише фактичні хвилини розмов вашому провайдеру SIP-телефонії."},
        {cat: "pricing", q: "Чи можна призупинити підписку?", a: "Так. Якщо ваш бізнес на паузі, ви можете заморозити акаунт на термін до 3 місяців. Вся клієнтська база та налаштування будуть збережені на серверах."},
        {cat: "pricing", q: "Оплата за SMS.", a: "Відправка SMS-нагадувань та розсилок тарифікується окремо і сплачується безпосередньо обраному вами провайдеру (наприклад, TurboSMS)."},
        {cat: "pricing", q: "Що буде при несплаті?", a: "При виникненні заборгованості ШІ-бот автоматично припиняє обробляти повідомлення клієнтів, проте ви зберігаєте повний доступ до адмін-панелі ще протягом 7 днів."},
        {cat: "pricing", q: "Вартість додаткової CRM.", a: "У Базовому тарифі безкоштовно доступна 1 інтеграція. За кожну наступну сторонню CRM або ERP систему діє доплата +1000 грн до щомісячної абонплати."},
        {cat: "pricing", q: "Персональний менеджер.", a: "Кожному клієнту безкоштовно виділяється персональний Onboarding-менеджер, який супроводжує процес налаштування та навчання персоналу в перші тижні."},
        {cat: "pricing", q: "Вартість розробки.", a: "Ціна створення кастомних модулів оцінюється індивідуально після складання детального Технічного Завдання (ТЗ) нашими архітекторами."},
        {cat: "pricing", q: "Оновлення системи.", a: "SafeOrbit є хмарним SaaS-рішенням. Всі мінорні та мажорні оновлення системи, нові патчі та вдосконалення безпеки застосовуються безкоштовно для всіх клієнтів."},
        {cat: "pricing", q: "Скільки операторів можна додати?", a: "Ми не обмежуємо кількість співробітників. Ви можете додати 10 майстрів і 3 адміністраторів — це ніяк не вплине на фінальну вартість тарифу."}
    ];

    let currentFaqCat = 'all';

    function renderFaqs(search = '') {
        const container = document.getElementById('faqAccordion');
        container.innerHTML = '';
        let html = '';
        let count = 0;
        
        faqs.forEach((faq, index) => {
            if(currentFaqCat !== 'all' && faq.cat !== currentFaqCat) return;
            if(search && !faq.q.toLowerCase().includes(search.toLowerCase()) && !faq.a.toLowerCase().includes(search.toLowerCase())) return;
            
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

    function searchFaq() {
        renderFaqs(document.getElementById('faqSearch').value);
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
