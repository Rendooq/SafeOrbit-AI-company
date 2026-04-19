import html
import io
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import urllib.parse


import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import (HTMLResponse, RedirectResponse,
                               StreamingResponse)
from sqlalchemy import and_, delete, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from dependencies import get_current_user
from models import (ActionLog, Appointment, Business, ChatLog, Customer,
                    CustomerSegment, GlobalPaymentSettings, Master, MasterService,
                    MonthlyPaymentLog, NPSReview, Product, Service, User,
                    AppointmentConfirmation, SystemUpdate)
from ui import get_layout # verify_password is removed
from utils import hash_password, log_action
from database import get_db, AsyncSessionLocal
from config import UA_TZ
import httpx
import logging

router = APIRouter(prefix="/superadmin", tags=["Superadmin"])


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def super_admin_page(sort: str = "date_desc", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin": return RedirectResponse("/", status_code=303)
    
    stmt = select(Business)
    if sort == "plan1":
        stmt = stmt.order_by(Business.plan_type.asc(), Business.id.desc())
    elif sort == "plan2":
        stmt = stmt.order_by(Business.plan_type.desc(), Business.id.desc())
    elif sort == "date_asc":
        stmt = stmt.order_by(Business.id.asc())
    else:
        stmt = stmt.order_by(Business.id.desc())
        
    bizs = (await db.execute(stmt)).scalars().all()
    
    users_owners = (await db.execute(select(User).where(User.role == 'owner'))).scalars().all()
    owner_map = {u.business_id: u.username for u in users_owners}
    
    counts = {}
    mrr = 0
    total_rev = 0
    active_clients = 0
    plan1_count = 0
    plan2_count = 0
    
    for b in bizs:
        c = await db.scalar(select(func.count(Appointment.id)).where(Appointment.business_id == b.id))
        counts[b.id] = c or 0
        if b.is_active and not b.parent_id:
            active_clients += 1
            if b.plan_type == 'plan1':
                mrr += 11000; total_rev += 9000; plan1_count += 1
            else:
                mrr += 53000; total_rev += 53000; plan2_count += 1

    payment_logs = (await db.execute(select(MonthlyPaymentLog).options(joinedload(MonthlyPaymentLog.business)).order_by(desc(MonthlyPaymentLog.payment_date)))).scalars().all()
    payment_rows = ""
    for pl in payment_logs:
        b_name = html.escape(pl.business.name) if pl.business else "Невідомо"
        rec_link = f"<a href='{pl.receipt_url}' target='_blank' class='btn btn-sm btn-outline-info'><i class='fas fa-file-invoice'></i> Чек</a>" if pl.receipt_url else "<span class='text-muted'>-</span>"
        date_str = pl.payment_date.strftime('%d.%m.%Y')
        payment_rows += f"<tr class='payment-row'><td>{date_str}</td><td><div class='fw-bold'>{b_name}</div></td><td class='fw-bold text-success'>{int(pl.amount or 0)} грн</td><td>{rec_link}</td><td class='small text-muted'>{html.escape(pl.notes or '')}</td><td class='text-end'><button class='btn btn-sm btn-outline-danger' onclick='deletePayment({pl.id})' title='Видалити платіж'><i class='fas fa-trash'></i></button></td></tr>"

    pending_bizs = [b for b in bizs if getattr(b, 'payment_status', 'approved') in ['pending', 'rejected'] and not b.parent_id]
    approved_bizs = [b for b in bizs if getattr(b, 'payment_status', 'approved') == 'approved']

    pending_rows = ""
    for b in pending_bizs:
        plan_badge = "<span class='badge bg-warning text-dark'>Базовий</span>" if b.plan_type == 'plan1' else "<span class='badge bg-primary'>PRO</span>"
        if getattr(b, 'subscription_discount', 0) > 0:
            if not b.discount_ends_at or b.discount_ends_at > datetime.now(UA_TZ).replace(tzinfo=None):
                d_end_str = b.discount_ends_at.strftime('%d.%m.%Y') if getattr(b, 'discount_ends_at', None) else 'назавжди'
                plan_badge += f" <span class='badge bg-danger' title='Знижка діє до {d_end_str}'>-{b.subscription_discount}%</span>"
        receipt_html = f"<a href='{b.receipt_url}' target='_blank' class='btn btn-sm btn-outline-info'><i class='fas fa-receipt'></i> Чек</a>" if getattr(b, 'receipt_url', None) else ""
        nda_html = f"<a href='{b.nda_url}' target='_blank' class='btn btn-sm btn-outline-primary'><i class='fas fa-file-signature'></i> NDA</a>" if getattr(b, 'nda_url', None) else ""
        contract_html = f"<a href='{b.contract_url}' target='_blank' class='btn btn-sm btn-outline-success'><i class='fas fa-file-contract'></i> Договір</a>" if getattr(b, 'contract_url', None) else ""
        utm_info = f"<br><span class='badge bg-light text-dark mt-1' style='font-size:9px;' title='Кампанія: {html.escape(b.utm_campaign or '')}'><i class='fas fa-link'></i> {html.escape(b.utm_source)} / {html.escape(b.utm_medium or '')}</span>" if getattr(b, 'utm_source', None) else ""
        
        if b.payment_status == 'rejected':
            status_html = f"{plan_badge}<br><span class='badge bg-danger mt-1'>Відхилено</span><br><small class='text-muted' style='font-size:10px;'>{html.escape(b.admin_message or '')}</small>"
            actions_html = f"<form action='/superadmin/approve-payment/{b.id}' method='post' class='d-inline'><button class='btn btn-sm btn-success me-2' title='Схвалити'><i class='fas fa-check'></i></button></form><button type='button' class='btn btn-sm btn-outline-danger' onclick='deleteBiz({b.id})' title='Видалити остаточно'><i class='fas fa-trash'></i></button>"
        else:
            status_html = plan_badge
            actions_html = f"<form action='/superadmin/approve-payment/{b.id}' method='post' class='d-inline'><button class='btn btn-sm btn-success me-2'><i class='fas fa-check me-1'></i>Схвалити</button></form><button type='button' class='btn btn-sm btn-danger' onclick='rejectPayment({b.id})'><i class='fas fa-times'></i></button>"
            
        pending_rows += f"<tr class='align-middle'><td><span class='text-muted'>#{b.id}</span></td><td><div class='fw-bold'>{html.escape(b.name)}</div><small class='text-muted'>{html.escape(b.type)}</small>{utm_info}</td><td>{status_html}</td><td><div class='d-flex gap-1'>{receipt_html}{nda_html}{contract_html}</div></td><td class='text-end'>{actions_html}</td></tr>"

    active_rows = ""
    docs_rows = ""
    for b in approved_bizs:
        plan_badge = "<span class='badge bg-warning text-dark'>Базовий</span>" if b.plan_type == 'plan1' else "<span class='badge bg-primary'>PRO</span>"
        if getattr(b, 'subscription_discount', 0) > 0:
            if not b.discount_ends_at or b.discount_ends_at > datetime.now(UA_TZ).replace(tzinfo=None):
                d_end_str = b.discount_ends_at.strftime('%d.%m.%Y') if getattr(b, 'discount_ends_at', None) else 'назавжди'
                plan_badge += f" <span class='badge bg-danger' title='Знижка діє до {d_end_str}'>-{b.subscription_discount}%</span>"
        parent_tag = "<br><span class='badge bg-info bg-opacity-10 text-info mt-1'><i class='fas fa-code-branch me-1'></i>Філія</span>" if b.parent_id else ""
        utm_info = f"<br><span class='badge bg-light text-dark mt-1' style='font-size:9px;' title='Кампанія: {html.escape(b.utm_campaign or '')}'><i class='fas fa-link'></i> {html.escape(b.utm_source)} / {html.escape(b.utm_medium or '')}</span>" if getattr(b, 'utm_source', None) else ""
        ai_badge = f"<span class='badge {'bg-primary' if b.has_ai_bot else 'bg-light text-muted'}'>ШІ: {'Увімк' if b.has_ai_bot else 'Вимк'}</span>"
        int_badge = f"<span class='badge {'bg-success' if getattr(b, 'integration_enabled', True) else 'bg-light text-muted'}'>CRM: {'Увімк' if getattr(b, 'integration_enabled', True) else 'Вимк'}</span>"
        
        doc_links = ""
        if getattr(b, 'nda_url', None): doc_links += f"<a href='{b.nda_url}' target='_blank' class='badge bg-danger text-white text-decoration-none me-1 mb-1' title='Завантажити NDA'><i class='fas fa-file-pdf'></i> NDA</a>"
        if getattr(b, 'contract_url', None): doc_links += f"<a href='{b.contract_url}' target='_blank' class='badge bg-success text-white text-decoration-none mb-1' title='Завантажити Договір'><i class='fas fa-file-pdf'></i> Договір</a>"
        if not doc_links: doc_links = "<span class='text-muted small'>-</span>"
        
        phone_esc = html.escape(owner_map.get(b.id, ''), quote=True)
        ctr_esc = html.escape(b.contract_url or '', quote=True)
        nda_esc = html.escape(b.nda_url or '', quote=True)
        iban_esc = html.escape(b.payment_iban or '', quote=True)
        card_esc = html.escape(b.payment_card_number or '', quote=True)
        receiver_esc = html.escape(b.payment_receiver_name or '', quote=True)
        qr_esc = html.escape(b.payment_qr_url or '', quote=True)
        d_end = b.discount_ends_at.strftime('%Y-%m-%d') if getattr(b, 'discount_ends_at', None) else ''
        active_rows += f"""<tr class='align-middle'>
                <td><span class='text-muted'>#{b.id}</span></td>
                <td><div class='fw-bold'>{html.escape(b.name)}</div><small class='text-muted'>{html.escape(b.type)}</small> {plan_badge} {parent_tag}{utm_info}</td>
                <td><span class='badge {'bg-success' if b.is_active else 'bg-danger'}'>{'АКТИВНИЙ' if b.is_active else 'ЗАБЛОКОВАНИЙ'}</span></td>
                <td class='text-muted small'>{counts.get(b.id, 0)} записів</td>
                <td><div class="d-flex flex-wrap" style="max-width: 140px;">{doc_links}</div></td>
                <td><div class="d-flex flex-column gap-1 align-items-start">{ai_badge}{int_badge}</div></td>
                <td class='text-end'>
                    <div class="btn-group">
                        <button class='btn btn-sm btn-outline-success' onclick="openPaymentModal({b.id}, '{html.escape(b.name, quote=True)}')" title="Фіксувати оплату"><i class='fas fa-hand-holding-usd'></i></button>
                        <button class='btn btn-sm btn-warning' onclick="editPaymentSettings({b.id}, '{iban_esc}', '{card_esc}', '{receiver_esc}', '{qr_esc}', '{html.escape(b.name, quote=True)}')" title="Реквізити для оплати"><i class='fas fa-credit-card'></i></button>
                        <a href='/superadmin/toggle/{b.id}' class='btn btn-sm btn-outline-secondary' title="Блокувати"><i class='fas fa-power-off'></i></a>
                        <button class='btn btn-sm btn-outline-info' onclick="editBiz({b.id}, '{phone_esc}', '{b.plan_type}', '{ctr_esc}', '{nda_esc}', {getattr(b, 'subscription_discount', 0)}, '{d_end}')" title="Редагувати клієнта"><i class='fas fa-edit'></i></button>
                        <a href='/superadmin/toggle-ai/{b.id}' class='btn btn-sm btn-outline-primary' title="AI Асистент"><i class='fas fa-robot'></i></a>
                        <a href='/superadmin/toggle-integration/{b.id}' class='btn btn-sm btn-outline-success' title="Увімк/Вимк CRM Інтеграції"><i class='fas fa-plug'></i></a>
                        <button class='btn btn-sm btn-outline-warning' onclick="resetPass({b.id}, '{html.escape(b.name, quote=True)}')" title="Скинути пароль"><i class='fas fa-key'></i></button>
                        <button class='btn btn-sm btn-outline-danger' onclick="deleteBiz({b.id})" title="Видалити"><i class='fas fa-trash'></i></button>
                    </div>
                </td>
            </tr>"""
        if not b.parent_id and (b.nda_url or b.contract_url):
            d_nda = f"<a href='{b.nda_url}' target='_blank' class='text-decoration-none'><i class='fas fa-file-pdf text-danger me-1'></i>NDA.pdf</a>" if b.nda_url else "<span class='text-muted'>-</span>"
            d_ctr = f"<a href='{b.contract_url}' target='_blank' class='text-decoration-none'><i class='fas fa-file-pdf text-success me-1'></i>Договір.pdf</a>" if b.contract_url else "<span class='text-muted'>-</span>"
            docs_rows += f"<tr class='align-middle'><td>#{b.id}</td><td class='fw-bold'>{html.escape(b.name)}</td><td>{d_nda}</td><td>{d_ctr}</td><td><span class='badge bg-success'>Підписано</span></td></tr>"

    updates = (await db.execute(select(SystemUpdate).order_by(desc(SystemUpdate.created_at)))).scalars().all()
    updates_rows = ""
    for u in updates:
        date_str = u.created_at.strftime('%d.%m.%Y %H:%M')
        title_json = html.escape(json.dumps(u.title))
        content_json = html.escape(json.dumps(u.content))
        updates_rows += f"<tr class='align-middle'><td><span class='text-muted'>#{u.id}</span></td><td><div class='fw-bold text-white'>{html.escape(u.title)}</div><small class='text-muted'>{date_str}</small></td><td class='text-end'><button class='btn btn-sm btn-outline-info me-1' onclick='editUpdate({u.id}, {title_json}, {content_json})'><i class='fas fa-edit'></i></button><form action='/superadmin/delete-update' method='post' class='d-inline' onsubmit=\"return confirm('Видалити?');\"><input type='hidden' name='id' value='{u.id}'><button class='btn btn-sm btn-outline-danger'><i class='fas fa-trash'></i></button></form></td></tr>"

    pending_badge = f'<span class="badge bg-danger ms-2">{len(pending_bizs)}</span>' if pending_bizs else ''
    
    sort_date_desc = 'selected' if sort == 'date_desc' else ''
    sort_date_asc = 'selected' if sort == 'date_asc' else ''
    sort_plan1 = 'selected' if sort == 'plan1' else ''
    sort_plan2 = 'selected' if sort == 'plan2' else ''

    content = f"""
    <div class="dashboard-stats mb-4">
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(52, 211, 153, 0.1); color: var(--success);"><i class="fas fa-money-bill-wave"></i></div>
            <div class="stat-info">
                <p class="stat-label">MRR (Щомісячний)</p>
                <h3 class="stat-value">{mrr} ₴</h3>
                <div class="stat-change text-success">+15% <i class="fas fa-arrow-up small"></i></div>
            </div>
        </div>
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(96, 165, 250, 0.1); color: var(--info);"><i class="fas fa-coins"></i></div>
            <div class="stat-info">
                <p class="stat-label">One-Time (Установки)</p>
                <h3 class="stat-value">{total_rev} ₴</h3>
                <div class="stat-change text-info">+8 нових</div>
            </div>
        </div>
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(175, 133, 255, 0.1); color: var(--accent-primary);"><i class="fas fa-users"></i></div>
            <div class="stat-info">
                <p class="stat-label">Активні Бізнеси</p>
                <h3 class="stat-value">{active_clients}</h3>
                <div class="stat-change" style="color: var(--accent-primary);">{plan1_count} базових / {plan2_count} pro</div>
            </div>
        </div>
        <div class="glass-card stat-card">
            <div class="stat-icon" style="background: rgba(244, 114, 182, 0.1); color: var(--accent-pink);"><i class="fas fa-bell"></i></div>
            <div class="stat-info">
                <p class="stat-label">Нові Заявки</p>
                <h3 class="stat-value">{len(pending_bizs)}</h3>
                <div class="stat-change text-danger">Потребують уваги</div>
            </div>
        </div>
    </div>
    
    <div class="glass-card mb-4 p-2 d-inline-flex flex-wrap" style="gap: 8px;">
        <ul class="nav nav-pills" id="saTabs" role="tablist" style="gap: 8px;">
            <li class="nav-item"><button class="nav-link active rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-dashboard"><i class="fas fa-chart-line me-2"></i>Аналітика</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-pending">
                <i class="fas fa-bell me-2"></i>Заявки {pending_badge}
            </button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-clients"><i class="fas fa-building me-2"></i>Бізнес-профілі</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-docs"><i class="fas fa-folder-open me-2"></i>Документи</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-payments"><i class="fas fa-money-check-alt me-2"></i>Фінанси</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-broadcast"><i class="fas fa-bullhorn me-2"></i>Розсилка</button></li>
            <li class="nav-item"><button class="nav-link rounded-pill px-4 fw-600" data-bs-toggle="pill" data-bs-target="#sa-updates"><i class="fas fa-newspaper me-2"></i>Оновлення</button></li>
        </ul>
        <div class="ms-auto d-flex gap-2 p-1">
            <a href="/superadmin/global-payment-settings" class="btn-glass px-4 py-2 rounded-pill text-decoration-none" style="font-size: 13px; background: rgba(175, 133, 255, 0.1); border-color: rgba(175, 133, 255, 0.2);"><i class="fas fa-globe me-2 text-primary"></i>Налаштувати тарифи</a>
        </div>
    </div>
    
    <div class="tab-content">
        <div class="tab-pane fade show active" id="sa-dashboard">
            <div class="row g-4">
                <div class="col-md-4">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4"><i class="fab fa-telegram text-primary me-2"></i>Системний Асистент</h6>
                        <form action="/superadmin/save-tg-settings" method="post">
                            <div class="mb-3"><label class="form-label">Bot Token</label><input name="tg_bot_token" class="glass-input" value="{user.tg_bot_token or ''}" placeholder="123456:ABC..."></div>
                            <div class="mb-4"><label class="form-label">Admin Chat ID</label><input name="tg_chat_id" class="glass-input" value="{user.tg_chat_id or ''}" placeholder="123456789"></div>
                            <button class="btn-primary-glow w-100 py-3">Зберегти налаштування</button>
                        </form>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4"><i class="fas fa-plus-circle text-success me-2"></i>Швидке створення бізнесу</h6>
                        <form action="/superadmin/add-sto" method="post" enctype="multipart/form-data">
                            <div class="row g-3 mb-3">
                                <div class="col-md-6"><label class="form-label">Назва</label><input name="name" class="glass-input" placeholder="Назва бізнесу" required></div>
                                <div class="col-md-6"><label class="form-label">Тип</label>
                                    <select name="type" class="form-select" onchange="document.getElementById('saRetailCatDiv').style.display = this.value === 'retail' ? 'block' : 'none';">
                                        <option value="barbershop">Салон краси</option>
                                        <option value="medical">Медицина</option>
                                        <option value="retail">Товарний бізнес</option>
                                        <option value="generic">Інше</option>
                                    </select>
                                </div>
                            </div>
                            <div class="mb-3" id="saRetailCatDiv" style="display:none;">
                                <label class="form-label">Категорія товарів</label>
                                <select name="retail_subcategory" class="form-select">
                                    <option value="clothing">Одяг</option>
                                    <option value="electronics">Електроніка</option>
                                </select>
                            </div>
                            <div class="row g-3 mb-3">
                                <div class="col-md-6"><label class="form-label">Телефон (Логін)</label><input name="phone" class="glass-input" placeholder="+380..." required></div>
                                <div class="col-md-6"><label class="form-label">Пароль</label><input name="p" type="password" class="glass-input" placeholder="••••••••" required></div>
                            </div>
                            <div class="mb-4"><label class="form-label">Тариф</label>
                                <select name="plan_type" class="form-select">
                                    <option value="plan1">Базовий</option>
                                    <option value="plan2">PRO</option>
                                </select>
                            </div>
                            <button class="btn-primary-glow w-100 py-3">Створити акаунт</button>
                      </form>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="tab-pane fade" id="sa-pending">
            <div class="glass-card p-4">
                <h6 class="fw-800 text-white mb-4">Заявки на активацію</h6>
                <div class="table-responsive">
                    <table class="glass-table">
                        <thead><tr><th>ID</th><th>Бізнес / Тип</th><th>Тариф</th><th>Документи</th><th class="text-end">Дії</th></tr></thead>
                        <tbody>{pending_rows if pending_rows else '<tr><td colspan="5" class="text-center py-5 text-muted">Нових заявок немає</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <div class="tab-pane fade" id="sa-clients">
            <div class="glass-card p-4">
                <div class="d-flex justify-content-between align-items-center mb-5 flex-wrap gap-3">
                    <h6 class="fw-800 text-white m-0">Активні Бізнеси</h6>
                    <div class="d-flex gap-3">
                        <select class="form-select w-auto" onchange="window.location.href='?sort='+this.value">
                            <option value="date_desc" {sort_date_desc}>Найновіші</option>
                            <option value="date_asc" {sort_date_asc}>Найстаріші</option>
                            <option value="plan1" {sort_plan1}>Тариф: 11к</option>
                            <option value="plan2" {sort_plan2}>Тариф: 53к</option>
                        </select>
                    </div>
                </div>
                <div class="table-responsive">
                    <table class="glass-table">
                        <thead><tr><th>ID</th><th>Бізнес / Тариф</th><th>Статус</th><th>Записи</th><th>Документи</th><th>Сервіси</th><th class="text-end">Дії</th></tr></thead>
                        <tbody>{active_rows if active_rows else '<tr><td colspan="7" class="text-center py-5 text-muted">Профілі гостей відсутні</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="tab-pane fade" id="sa-docs">
            <div class="glass-card p-4">
                <h6 class="fw-800 text-white mb-4">Реєстр Договорів та NDA</h6>
                <div class="table-responsive">
                    <table class="glass-table">
                        <thead><tr><th>ID</th><th>Бізнес</th><th>NDA</th><th>Договір</th><th>Статус</th></tr></thead>
                        <tbody>{docs_rows if docs_rows else '<tr><td colspan="5" class="text-center py-5 text-muted">Документи ще не завантажені</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <div class="tab-pane fade" id="sa-payments">
            <div class="glass-card p-4">
                <div class="d-flex justify-content-between align-items-center flex-wrap gap-3 mb-5">
                    <div>
                        <h6 class="fw-800 text-white mb-1">Фінансовий Журнал</h6>
                        <p class="text-muted small mb-0">Історія щомісячних платежів за підписку</p>
                    </div>
                    <div class="d-flex gap-2">
                        <input type="text" id="paymentSearch" onkeyup="filterPayments()" class="glass-input" style="max-width: 250px;" placeholder="Пошук по базі...">
                        <a href="/superadmin/export-payments" class="btn-glass py-2"><i class="fas fa-file-csv me-2 text-success"></i>Експорт</a>
                    </div>
                </div>
                <div class="table-responsive">
                    <table class="glass-table">
                        <thead><tr><th>Дата</th><th>Бізнес</th><th>Сума</th><th>Чек</th><th>Коментар</th><th class="text-end">Дії</th></tr></thead>
                        <tbody>{payment_rows if payment_rows else '<tr><td colspan="6" class="text-center py-5 text-muted">Платежів ще не було</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="tab-pane fade" id="sa-broadcast">
            <div class="glass-card p-5" style="max-width: 800px; margin: 0 auto;">
                <div class="text-center mb-5">
                    <div class="logo-icon mb-4" style="width: 80px; height: 80px; margin: 0 auto; background: rgba(251, 191, 36, 0.1); color: var(--warning); font-size: 32px; border-radius: 24px; border: 0.5px solid rgba(251, 191, 36, 0.2);"><i class="fas fa-bullhorn"></i></div>
                    <h4 class="fw-800 text-white" style="font-size: 28px; letter-spacing: -1px;">Глобальна розсилка</h4>
                    <p class="text-muted small fw-500">Ваше повідомлення побачать усі власники бізнесів у своїй панелі керування</p>
                </div>
                <form action="/superadmin/broadcast" method="post">
                    <div class="mb-4">
                        <textarea name="message" class="glass-input" rows="8" style="border-radius: 24px !important;" placeholder="Введіть текст оголошення..." required></textarea>
                    </div>
                    <button type="submit" class="btn-primary-glow w-100 py-3"><i class="fas fa-paper-plane me-2"></i>Відправити розсилку</button>
                </form>
            </div>
        </div>
        
        <div class="tab-pane fade" id="sa-updates">
            <div class="row g-4">
                <div class="col-md-5">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4">Опублікувати новину</h6>
                        <form action="/superadmin/add-update" method="post">
                            <div class="mb-3"><label class="form-label">Заголовок</label><input name="title" class="glass-input" required></div>
                            <div class="mb-4"><label class="form-label">Текст новини / Порада</label><textarea name="content" class="glass-input" rows="8" required></textarea></div>
                            <button class="btn-primary-glow w-100 py-3">Опублікувати</button>
                        </form>
                    </div>
                </div>
                <div class="col-md-7">
                    <div class="glass-card p-4">
                        <h6 class="fw-800 text-white mb-4">Історія оновлень</h6>
                        <div class="table-responsive">
                            <table class="glass-table">
                                <thead><tr><th>ID</th><th>Заголовок та Дата</th><th class="text-end">Дії</th></tr></thead>
                                <tbody>{updates_rows if updates_rows else '<tr><td colspan="3" class="text-center py-5 text-muted">Новин ще немає</td></tr>'}</tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Modals (iOS 26 Style) -->
    <div class="modal fade" id="resetModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Скинути пароль</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/superadmin/reset-password" method="post" class="d-flex flex-column h-100">
            <div class="modal-body overflow-y-auto">
                <input type="hidden" name="id" id="resetId">
                <p class="text-muted mb-4">Встановлення нового пароля для: <strong id="resetName" class="text-white"></strong></p>
                <input name="new_password" class="glass-input" required placeholder="Введіть новий пароль">
            </div>
            <div class="modal-footer"><button class="btn-primary-glow w-100 py-3">Оновити пароль</button></div>
        </form>
    </div></div></div>

    <div class="modal fade" id="editBizModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Редагування клієнта</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/superadmin/edit-business" method="post" class="d-flex flex-column h-100">
            <div class="modal-body overflow-y-auto">
                <input type="hidden" name="id" id="editBizId">
                <div class="mb-3"><label class="form-label">Телефон (Логін)</label><input name="phone" id="editBizPhone" class="glass-input"></div>
                <div class="row g-3 mb-3">
                    <div class="col-md-12"><label class="form-label">Тариф</label>
                        <select name="plan_type" id="editBizPlan" class="form-select">
                            <option value="plan1">Базовий</option>
                            <option value="plan2">PRO</option>
                        </select>
                    </div>
                    <div class="col-12 col-md-6"><label class="form-label">Знижка (%)</label><input name="subscription_discount" type="number" min="0" max="100" id="editBizDiscount" class="glass-input" value="0"></div>
                    <div class="col-12 col-md-6"><label class="form-label">Діє до</label><input name="discount_ends_at" type="date" id="editBizDiscountEnd" class="glass-input"></div>
                </div>
                <div class="mb-3"><label class="form-label">URL Договору</label><input name="contract_url" id="editBizContract" class="glass-input"></div>
                <div class="mb-0"><label class="form-label">URL NDA</label><input name="nda_url" id="editBizNda" class="glass-input"></div>
            </div>
            <div class="modal-footer"><button class="btn-primary-glow w-100 py-3">Зберегти</button></div>
        </form>
    </div></div></div>

    <div class="modal fade" id="paymentModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Фіксація оплати</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/superadmin/log-payment" method="post" class="d-flex flex-column h-100">
            <div class="modal-body overflow-y-auto">
                <input type="hidden" name="id" id="paymentBizId">
                <p class="text-muted mb-4">Оплата для: <strong id="paymentBizName" class="text-white"></strong></p>
                <div class="mb-3"><label class="form-label">Сума (грн)</label><input name="amount" type="number" class="glass-input" required></div>
                <div class="mb-3"><label class="form-label">URL Чеку (необов'язково)</label><input name="receipt_url" class="glass-input"></div>
                <div class="mb-0"><label class="form-label">Коментар</label><input name="notes" class="glass-input"></div>
            </div>
            <div class="modal-footer"><button class="btn-primary-glow w-100 py-3">Зафіксувати платіж</button></div>
        </form>
    </div></div></div>

    <div class="modal fade" id="paymentSettingsModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Реквізити для оплати</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/superadmin/save-payment-settings" method="post" class="d-flex flex-column h-100">
            <div class="modal-body overflow-y-auto">
                <input type="hidden" name="id" id="paymentSettingsBizId">
                <p class="text-muted mb-4">Реквізити для: <strong id="paymentSettingsBizName" class="text-white"></strong></p>
                <div class="mb-3"><label class="form-label">IBAN</label><input name="iban" id="paymentIban" class="glass-input"></div>
                <div class="mb-3"><label class="form-label">Номер картки</label><input name="card" id="paymentCard" class="glass-input"></div>
                <div class="mb-3"><label class="form-label">Отримувач</label><input name="receiver" id="paymentReceiver" class="glass-input"></div>
                <div class="mb-0"><label class="form-label">URL QR-коду</label><input name="qr_url" id="paymentQr" class="glass-input"></div>
            </div>
            <div class="modal-footer"><button class="btn-primary-glow w-100 py-3">Зберегти реквізити</button></div>
        </form>
    </div></div></div>

    <div class="modal fade" id="editUpdateModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered w-full max-w-md mx-auto"><div class="modal-content max-h-85vh overflow-hidden flex-col">
        <div class="modal-header"><h5 class="modal-title">Редагувати новину</h5><button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>
        <form action="/superadmin/edit-update" method="post" class="d-flex flex-column h-100">
            <div class="modal-body overflow-y-auto">
                <input type="hidden" name="id" id="editUpdId">
                <div class="mb-3"><label class="form-label">Заголовок</label><input name="title" id="editUpdTitle" class="glass-input" required></div>
                <div class="mb-0"><label class="form-label">Текст</label><textarea name="content" id="editUpdContent" class="glass-input" rows="8" required></textarea></div>
            </div>
            <div class="modal-footer"><button class="btn-primary-glow w-100 py-3">Зберегти зміни</button></div>
        </form>
    </div></div></div>
    """

    scripts = """
    <script>
    function filterPayments() {
        let q = document.getElementById('paymentSearch').value.toLowerCase();
        document.querySelectorAll('.payment-row').forEach(row => {
            row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
        });
    }
    function deleteBiz(id) {
        Swal.fire({ title: 'Видалити бізнес?', text: "Це видалить всі дані, включаючи записи та клієнтів!", icon: 'warning', showCancelButton: true, confirmButtonColor: '#ef4444', confirmButtonText: 'Так, видалити', cancelButtonText: 'Скасувати', background: 'rgba(20, 20, 25, 0.95)', color: '#fff', customClass: { popup: 'glass-card' } }).then(r => { if(r.isConfirmed) window.location.href = '/superadmin/delete/' + id; });
    }
    function deletePayment(id) {
        Swal.fire({ title: 'Видалити платіж?', icon: 'warning', showCancelButton: true, confirmButtonColor: '#ef4444', confirmButtonText: 'Так, видалити', cancelButtonText: 'Скасувати', background: 'rgba(20, 20, 25, 0.95)', color: '#fff', customClass: { popup: 'glass-card' } }).then(r => { if(r.isConfirmed) window.location.href = '/superadmin/delete-payment/' + id; });
    }
    function rejectPayment(id) {
        Swal.fire({ title: 'Відхилити заявку?', input: 'textarea', inputLabel: 'Причина відмови (побачить клієнт)', inputPlaceholder: 'Наприклад: Неякісний чек / Невірні дані', icon: 'warning', showCancelButton: true, confirmButtonColor: '#ef4444', confirmButtonText: 'Відхилити', cancelButtonText: 'Скасувати', background: 'rgba(20, 20, 25, 0.95)', color: '#fff', customClass: { popup: 'glass-card' } }).then(r => { if(r.isConfirmed) { const form = document.createElement('form'); form.method = 'POST'; form.action = '/superadmin/reject-payment/' + id; const input = document.createElement('input'); input.type = 'hidden'; input.name = 'reason'; input.value = r.value || ''; form.appendChild(input); document.body.appendChild(form); form.submit(); } });
    }
    function openPaymentModal(id, name) {
        document.getElementById('paymentBizId').value = id;
        document.getElementById('paymentBizName').innerText = name;
        new bootstrap.Modal(document.getElementById('paymentModal')).show();
    }
    function editPaymentSettings(id, iban, card, receiver, qr, name) {
        document.getElementById('paymentSettingsBizId').value = id;
        document.getElementById('paymentSettingsBizName').innerText = name;
        document.getElementById('paymentIban').value = iban;
        document.getElementById('paymentCard').value = card;
        document.getElementById('paymentReceiver').value = receiver;
        document.getElementById('paymentQr').value = qr;
        new bootstrap.Modal(document.getElementById('paymentSettingsModal')).show();
    }
    function editBiz(id, phone, plan, contract, nda, discount, discountEnd) {
        document.getElementById('editBizId').value = id;
        document.getElementById('editBizPhone').value = phone;
        document.getElementById('editBizPlan').value = plan;
        document.getElementById('editBizContract').value = contract;
        document.getElementById('editBizNda').value = nda;
        document.getElementById('editBizDiscount').value = discount;
        document.getElementById('editBizDiscountEnd').value = discountEnd;
        new bootstrap.Modal(document.getElementById('editBizModal')).show();
    }
    function resetPass(id, name) {
        document.getElementById('resetId').value = id;
        document.getElementById('resetName').innerText = name;
        new bootstrap.Modal(document.getElementById('resetModal')).show();
    }
    function editUpdate(id, title, content) {
        document.getElementById('editUpdId').value = id;
        document.getElementById('editUpdTitle').value = title;
        document.getElementById('editUpdContent').value = content;
        new bootstrap.Modal(document.getElementById('editUpdateModal')).show();
    }
    </script>
    """
    return get_layout(content, user, "super", scripts=scripts)


@router.post("/add-sto", include_in_schema=False)
async def add_sto(
    name: str = Form(...),
    type: str = Form(...),
    retail_subcategory: Optional[str] = Form(None),
    phone: str = Form(...),
    p: str = Form(...),
    plan_type: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    existing_user = await db.scalar(select(User).where(User.username == phone))
    if existing_user:
        return RedirectResponse("/superadmin?msg=login_exists", status_code=303)

    new_biz = Business(
        name=name,
        type=type,
        retail_subcategory=retail_subcategory if type == 'retail' else None,
        plan_type=plan_type,
        is_active=True,
        payment_status="approved"
    )
    db.add(new_biz)
    await db.flush()
    await db.refresh(new_biz)

    new_user = User(username=phone, password=hash_password(p), role="owner", business_id=new_biz.id)
    db.add(new_user)
    await db.commit()

    await log_action(db, new_biz.id, user.id, "Створено бізнес", f"Бізнес '{name}' ({type}) додано супер-адміном.")

    return RedirectResponse("/superadmin?msg=added", status_code=303)


@router.post("/approve-payment/{business_id}", include_in_schema=False)
async def approve_payment(business_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, business_id)
    if biz:
        biz.payment_status = "approved"
        biz.is_active = True
        await db.commit()
        await log_action(db, biz.id, user.id, "Схвалено платіж", f"Платіж для бізнесу '{biz.name}' схвалено.")

        # Notify business owner
        owner_user = await db.scalar(select(User).where(User.business_id == biz.id).where(User.role == 'owner'))
        if owner_user and biz.telegram_token and owner_user.tg_chat_id:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                        json={"chat_id": owner_user.tg_chat_id, "text": "✅ Ваш акаунт SafeOrbit активовано! Ласкаво просимо!"}
                    )
            except Exception as e:
                logging.error(f"Failed to send activation notification to business {biz.id} owner: {e}")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.post("/reject-payment/{business_id}", include_in_schema=False)
async def reject_payment(business_id: int, reason: str = Form(""), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, business_id)
    if biz:
        biz.payment_status = "rejected"
        biz.is_active = False
        biz.admin_message = reason
        await db.commit()
        await log_action(db, biz.id, user.id, "Відхилено заявку", f"Заявку бізнесу '{biz.name}' відхилено. Причина: {reason}")
        
    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.get("/toggle/{business_id}", include_in_schema=False)
async def toggle_business_active(business_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, business_id)
    if biz:
        biz.is_active = not biz.is_active
        await db.commit()
        action_text = "Активовано" if biz.is_active else "Заблоковано"
        await log_action(db, biz.id, user.id, action_text, f"Бізнес '{biz.name}' {action_text.lower()} супер-адміном.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.get("/toggle-ai/{business_id}", include_in_schema=False)
async def toggle_business_ai(business_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, business_id)
    if biz:
        biz.has_ai_bot = not biz.has_ai_bot
        await db.commit()
        action_text = "Увімкнено AI" if biz.has_ai_bot else "Вимкнено AI"
        await log_action(db, biz.id, user.id, action_text, f"AI для бізнесу '{biz.name}' {action_text.lower()} супер-адміном.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.get("/toggle-integration/{business_id}", include_in_schema=False)
async def toggle_business_integration(business_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, business_id)
    if biz:
        biz.integration_enabled = not biz.integration_enabled
        await db.commit()
        action_text = "Увімкнено інтеграції" if biz.integration_enabled else "Вимкнено інтеграції"
        await log_action(db, biz.id, user.id, action_text, f"Інтеграції для бізнесу '{biz.name}' {action_text.lower()} супер-адміном.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.post("/reset-password", include_in_schema=False)
async def reset_password(id: int = Form(...), new_password: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    target_user = await db.get(User, id)
    if target_user:
        target_user.password = hash_password(new_password)
        await db.commit()
        await log_action(db, target_user.business_id, user.id, "Скинуто пароль", f"Пароль для користувача '{target_user.username}' скинуто супер-адміном.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.post("/edit-business", include_in_schema=False)
async def edit_business(
    id: int = Form(...),
    phone: str = Form(...),
    plan_type: str = Form(...),
    subscription_discount: int = Form(0),
    discount_ends_at: Optional[str] = Form(None),
    contract_url: Optional[str] = Form(None),
    nda_url: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, id)
    if biz:
        biz.plan_type = plan_type
        biz.contract_url = contract_url # Keep contract_url
        biz.nda_url = nda_url
        biz.subscription_discount = subscription_discount
        if discount_ends_at:
            try:
                biz.discount_ends_at = datetime.strptime(discount_ends_at, "%Y-%m-%d").replace(hour=23, minute=59)
            except ValueError: pass
        else:
            biz.discount_ends_at = None
        
        owner_user = await db.scalar(select(User).where(User.business_id == biz.id).where(User.role == 'owner'))
        if owner_user:
            owner_user.username = phone

        await db.commit()
        await log_action(db, biz.id, user.id, "Редаговано бізнес", f"Дані бізнесу '{biz.name}' оновлено супер-адміном.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.post("/log-payment", include_in_schema=False)
async def log_payment(
    id: int = Form(...),
    amount: float = Form(...),
    receipt_url: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    new_log = MonthlyPaymentLog(
        business_id=id,
        amount=amount,
        receipt_url=receipt_url,
        notes=notes,
        payment_date=datetime.now(UA_TZ).replace(tzinfo=None)
    )
    db.add(new_log)
    await db.commit()
    biz = await db.get(Business, id)
    await log_action(db, id, user.id, "Зафіксовано платіж", f"Зафіксовано платіж {amount} грн для бізнесу '{biz.name}'.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.post("/save-payment-settings", include_in_schema=False)
async def save_payment_settings(
    id: int = Form(...),
    iban: Optional[str] = Form(None),
    card: Optional[str] = Form(None),
    receiver: Optional[str] = Form(None),
    qr_url: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, id)
    if biz:
        biz.payment_iban = iban
        biz.payment_card_number = card
        biz.payment_receiver_name = receiver
        biz.payment_qr_url = qr_url
        await db.commit()
        await log_action(db, id, user.id, "Оновлено реквізити", f"Реквізити для бізнесу '{biz.name}' оновлено супер-адміном.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.get("/delete/{business_id}", include_in_schema=False)
async def delete_business(business_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    biz = await db.get(Business, business_id)
    if biz:
        # Спочатку видаляємо всі вкладені зв'язки, щоб уникнути помилок Foreign Key
        masters_subq = select(Master.id).where(Master.business_id == business_id)
        await db.execute(delete(MasterService).where(MasterService.master_id.in_(masters_subq)))
        
        appts_subq = select(Appointment.id).where(Appointment.business_id == business_id)
        await db.execute(delete(AppointmentConfirmation).where(AppointmentConfirmation.appointment_id.in_(appts_subq)))

        await db.execute(delete(NPSReview).where(NPSReview.business_id == business_id))
        await db.execute(delete(CustomerSegment).where(CustomerSegment.business_id == business_id))

        # Delete associated users
        await db.execute(delete(User).where(User.business_id == business_id))
        # Delete associated appointments
        await db.execute(delete(Appointment).where(Appointment.business_id == business_id))
        # Delete associated customers
        await db.execute(delete(Customer).where(Customer.business_id == business_id))
        # Delete associated masters
        await db.execute(delete(Master).where(Master.business_id == business_id))
        # Delete associated services
        await db.execute(delete(Service).where(Service.business_id == business_id))
        # Delete associated products
        await db.execute(delete(Product).where(Product.business_id == business_id))
        # Delete associated monthly payment logs
        await db.execute(delete(MonthlyPaymentLog).where(MonthlyPaymentLog.business_id == business_id))
        # Delete associated action logs
        await db.execute(delete(ActionLog).where(ActionLog.business_id == business_id))
        # Delete associated chat logs
        await db.execute(delete(ChatLog).where(ChatLog.business_id == business_id))

        await db.delete(biz)
        await db.commit()
        
        # Логуємо видалення без прив'язки до business_id, оскільки бізнес вже видалено
        await log_action(db, None, user.id, "Видалено бізнес", f"Бізнес '{biz.name}' видалено супер-адміном.")

    return RedirectResponse("/superadmin?msg=deleted", status_code=303)


@router.get("/delete-payment/{payment_log_id}", include_in_schema=False)
async def delete_payment_log(payment_log_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    payment_log = await db.get(MonthlyPaymentLog, payment_log_id)
    if payment_log:
        biz_id = payment_log.business_id
        await db.delete(payment_log)
        await db.commit()
        await log_action(db, biz_id, user.id, "Видалено платіж", f"Платіж ID:{payment_log_id} видалено супер-адміном.")

    return RedirectResponse("/superadmin?msg=deleted", status_code=303)


@router.post("/save-tg-settings", include_in_schema=False)
async def save_superadmin_tg_settings(
    tg_bot_token: str = Form(None),
    tg_chat_id: str = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    user.tg_bot_token = tg_bot_token
    user.tg_chat_id = tg_chat_id
    await db.commit()
    await log_action(db, None, user.id, "Оновлено Telegram налаштування", "Telegram налаштування супер-адміна оновлено.")

    return RedirectResponse("/superadmin?msg=saved", status_code=303)


@router.post("/broadcast", include_in_schema=False)
async def broadcast_message(
    message: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    businesses = (await db.execute(select(Business).where(Business.is_active == True))).scalars().all()
    
    for biz in businesses:
        owner_user = await db.scalar(select(User).where(User.business_id == biz.id).where(User.role == 'owner'))
        if owner_user and biz.telegram_token and owner_user.tg_chat_id:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                        json={"chat_id": owner_user.tg_chat_id, "text": f"📢 Оголошення від SafeOrbit:\n\n{message}"}
                    )
            except Exception as e:
                logging.error(f"Failed to send broadcast to business {biz.id} owner: {e}")

    await log_action(db, None, user.id, "Розсилка", message)

    return RedirectResponse("/superadmin?msg=broadcast_sent", status_code=303)


@router.get("/global-payment-settings", response_class=HTMLResponse, include_in_schema=False)
async def global_payment_settings_page(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)

    settings = await db.scalar(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))
    if not settings:
        settings = GlobalPaymentSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    plan1_check = 'checked' if settings.is_plan1_active else ''
    plan2_check = 'checked' if settings.is_plan2_active else ''

    try:
        if settings.promo_code and settings.promo_code.strip().startswith('['):
            promos = json.loads(settings.promo_code)
        elif settings.promo_code:
            promos = [{
                "code": settings.promo_code,
                "discount": settings.promo_discount or 0,
                "plan": getattr(settings, 'promo_target_plan', 'all'),
                "expires": settings.promo_expires_at.strftime('%Y-%m-%d') if getattr(settings, 'promo_expires_at', None) else "",
                "duration": getattr(settings, 'discount_duration_months', 0)
            }]
        else:
            promos = []
    except:
        promos = []
        
    promos_html = ""
    for i, p in enumerate(promos):
        promos_html += f"""
        <div class="promo-row row g-3 mb-3 align-items-end" id="promo_row_{i}">
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Промокод</label><input type="text" name="promo_code_list[]" class="glass-input" value="{html.escape(p['code'])}" placeholder="START20" required></div>
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Знижка (%)</label><input type="number" min="1" max="100" name="promo_discount_list[]" class="glass-input" value="{p['discount']}" required></div>
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Тариф</label>
                <select name="promo_plan_list[]" class="form-select">
                    <option value="all" {'selected' if p['plan'] == 'all' else ''}>Всі</option>
                    <option value="plan1" {'selected' if p['plan'] == 'plan1' else ''}>Базовий</option>
                    <option value="plan2" {'selected' if p['plan'] == 'plan2' else ''}>PRO</option>
                </select>
            </div>
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Діє міс. (0=назавжди)</label><input type="number" min="0" name="promo_duration_list[]" class="glass-input" value="{p.get('duration', 0)}"></div>
            <div class="col-10 col-md-3"><label class="form-label text-muted small">Діє до (дата)</label><input type="date" name="promo_expires_list[]" class="glass-input" value="{p.get('expires', '')}"></div>
            <div class="col-2 col-md-1"><button type="button" class="btn btn-glass w-100 text-danger" onclick="document.getElementById('promo_row_{i}').remove()"><i class="fas fa-trash"></i></button></div>
        </div>
        """

    content = f"""
    <div class="glass-card p-5" style="max-width: 800px; margin: 0 auto;">
        <h4 class="fw-800 text-white mb-4">Глобальні Налаштування Оплати</h4>
        <p class="text-muted small mb-5">Ці налаштування відображаються на сторінці реєстрації для всіх нових бізнесів.</p>
        <form action="/superadmin/save-global-payment-settings" method="post">
            <div class="mb-3"><label class="form-label">IBAN</label><input name="iban" class="glass-input" value="{html.escape(settings.iban or '')}" placeholder="UAXXXXXXXXXXXXXXXXXXXXXXXXX"></div>
            <div class="mb-3"><label class="form-label">Номер картки</label><input name="card_number" class="glass-input" value="{html.escape(settings.card_number or '')}" placeholder="XXXX XXXX XXXX XXXX"></div>
            <div class="mb-3"><label class="form-label">Отримувач</label><input name="receiver_name" class="glass-input" value="{html.escape(settings.receiver_name or '')}" placeholder="ПІБ або Назва компанії"></div>
            <div class="mb-3"><label class="form-label">Назва банку</label><input name="bank_name" class="glass-input" value="{html.escape(settings.bank_name or '')}" placeholder="Monobank"></div>
            <div class="mb-4"><label class="form-label">URL QR-коду</label><input name="qr_url" class="glass-input" value="{html.escape(settings.qr_url or '')}" placeholder="https://example.com/qr.png"></div>
            
            <div class="form-check form-switch mb-3">
                <input class="form-check-input" type="checkbox" name="is_plan1_active" id="isPlan1Active" {plan1_check}>
                <label class="form-check-label text-white" for="isPlan1Active">Активувати Базовий Тариф (11 000 грн/міс)</label>
            </div>
            <div class="form-check form-switch mb-5">
                <input class="form-check-input" type="checkbox" name="is_plan2_active" id="isPlan2Active" {plan2_check}>
                <label class="form-check-label text-white" for="isPlan2Active">Активувати PRO Тариф (53 000 грн)</label>
            </div>

            <div class="row g-3 mb-5">
                <div class="col-md-6">
                    <label class="form-label">Знижка на Базовий Тариф (%)</label>
                    <input type="number" min="0" max="100" name="plan1_discount" class="glass-input" value="{settings.plan1_discount or 0}">
                </div>
                <div class="col-md-6">
                    <label class="form-label">Знижка на PRO Тариф (%)</label>
                    <input type="number" min="0" max="100" name="plan2_discount" class="glass-input" value="{settings.plan2_discount or 0}">
                </div>
            </div>

            <div class="mb-5">
                <label class="form-label text-white mb-3">Система Промокодів</label>
                <div id="promocodes-container">
                    {promos_html}
                </div>
                <button type="button" class="btn-glass py-2 px-4 mt-2" onclick="addPromoCode()">
                    <i class="fas fa-plus me-2 text-primary"></i>Додати Промокод
                </button>
            </div>

            <button type="submit" class="btn-primary-glow w-100 py-3">Зберегти Глобальні Налаштування</button>
        </form>
    </div>
    <script>
    function addPromoCode() {{
        const container = document.getElementById('promocodes-container');
        const index = container.children.length;
        const html = `
            <div class="promo-row row g-3 mb-3 align-items-end" id="promo_row_${{index}}">
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Промокод</label><input type="text" name="promo_code_list[]" class="glass-input" placeholder="START20" required></div>
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Знижка (%)</label><input type="number" min="1" max="100" name="promo_discount_list[]" class="glass-input" value="10" required></div>
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Тариф</label>
                    <select name="promo_plan_list[]" class="form-select">
                        <option value="all">Всі</option>
                        <option value="plan1">Базовий</option>
                        <option value="plan2">PRO</option>
                    </select>
                </div>
            <div class="col-6 col-md-2"><label class="form-label text-muted small">Діє міс. (0=назавжди)</label><input type="number" min="0" name="promo_duration_list[]" class="glass-input" value="0"></div>
            <div class="col-10 col-md-3"><label class="form-label text-muted small">Діє до (дата)</label><input type="date" name="promo_expires_list[]" class="glass-input"></div>
                <div class="col-2 col-md-1"><button type="button" class="btn btn-glass w-100 text-danger" onclick="document.getElementById('promo_row_${{index}}').remove()"><i class="fas fa-trash"></i></button></div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', html);
    }}
    </script>
    """
    return get_layout(content, user, "super", scripts="")


@router.post("/save-global-payment-settings", include_in_schema=False)
async def save_global_payment_settings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)
        
    form_data = await request.form()

    settings = await db.scalar(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))
    if not settings:
        settings = GlobalPaymentSettings(id=1)
        db.add(settings)
        await db.flush()

    settings.iban = form_data.get('iban')
    settings.card_number = form_data.get('card_number')
    settings.receiver_name = form_data.get('receiver_name')
    settings.qr_url = form_data.get('qr_url')
    settings.bank_name = form_data.get('bank_name')
    settings.is_plan1_active = form_data.get('is_plan1_active') == 'on'
    settings.is_plan2_active = form_data.get('is_plan2_active') == 'on'
    try: settings.plan1_discount = int(form_data.get('plan1_discount') or 0)
    except: settings.plan1_discount = 0
    try: settings.plan2_discount = int(form_data.get('plan2_discount') or 0)
    except: settings.plan2_discount = 0
    
    promos = []
    codes = form_data.getlist('promo_code_list[]')
    discounts = form_data.getlist('promo_discount_list[]')
    plans = form_data.getlist('promo_plan_list[]')
    expires = form_data.getlist('promo_expires_list[]')
    durations = form_data.getlist('promo_duration_list[]')
    
    for c, d, p, e, dur in zip(codes, discounts, plans, expires, durations):
        if c.strip():
            try: disc_val = int(d)
            except: disc_val = 0
            try: dur_val = int(dur)
            except: dur_val = 0
            promos.append({"code": c.strip().upper(), "discount": disc_val, "plan": p, "expires": e, "duration": dur_val})
            
    settings.promo_code = json.dumps(promos)
        
    settings.updated_at = datetime.now(UA_TZ).replace(tzinfo=None)

    await db.commit()
    await log_action(db, None, user.id, "Оновлено глобальні реквізити", "Глобальні платіжні реквізити оновлено супер-адміном.")

    return RedirectResponse("/superadmin/global-payment-settings?msg=saved", status_code=303)


@router.get("/export-payments", include_in_schema=False)
async def export_payments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)
    
    stmt = select(MonthlyPaymentLog).options(joinedload(MonthlyPaymentLog.business)).order_by(desc(MonthlyPaymentLog.payment_date))
    res = await db.execute(stmt)
    logs = res.scalars().all()
    
    data = []
    for pl in logs:
        data.append({
            "ID": pl.id,
            "Дата оплати": pl.payment_date.strftime('%Y-%m-%d'),
            "Клієнт (Бізнес)": pl.business.name if pl.business else "Невідомо",
            "Сума (грн)": pl.amount,
            "Нотатки": pl.notes or "",
            "Посилання на чек": pl.receipt_url or ""
        })
    
    df = pd.DataFrame(data)
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    
    response = StreamingResponse(iter([stream.getvalue().encode('utf-8-sig')]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=payments_export.csv"
    return response

@router.post("/add-update", include_in_schema=False)
async def add_update(title: str = Form(...), content: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)
    db.add(SystemUpdate(title=title, content=content, created_at=datetime.now(UA_TZ).replace(tzinfo=None)))
    await db.commit()
    return RedirectResponse("/superadmin?msg=saved", status_code=303)

@router.post("/edit-update", include_in_schema=False)
async def edit_update(id: int = Form(...), title: str = Form(...), content: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)
    u = await db.get(SystemUpdate, id)
    if u:
        u.title = title
        u.content = content
        await db.commit()
    return RedirectResponse("/superadmin?msg=saved", status_code=303)

@router.post("/delete-update", include_in_schema=False)
async def delete_update(id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user or user.role != "superadmin":
        return RedirectResponse("/", status_code=303)
    u = await db.get(SystemUpdate, id)
    if u:
        await db.delete(u)
        await db.commit()
    return RedirectResponse("/superadmin?msg=deleted", status_code=303)