import html
import logging
from typing import Optional
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import LABELS
from database import get_db
from models import ActionLog, Appointment, Business, Customer, Master, Service
from services.integrations import (push_to_beauty_pro, push_to_cleverbox,
                                    push_to_integrica, push_to_luckyfit,
                                    push_to_uspacy)
from services.notifications import send_new_appointment_notifications

router = APIRouter(prefix="/widget", tags=["Widget"])
logger = logging.getLogger(__name__)

@router.get("/{business_id}")
async def public_booking_widget(business_id: int, db: AsyncSession = Depends(get_db)):
    biz = await db.get(Business, business_id)
    if not biz or not biz.is_active: 
        return HTMLResponse("Бізнес не знайдено або заблоковано", status_code=404)
    
    services = (await db.execute(select(Service).where(Service.business_id == business_id))).scalars().all()
    masters = (await db.execute(select(Master).where(and_(Master.business_id == business_id, Master.is_active == True)))).scalars().all()
    
    s_opts = "".join([f"<option value='{s.name}'>{s.name} ({s.price} грн)</option>" for s in services])
    m_opts = "".join([f"<option value='{m.id}'>{m.name}</option>" for m in masters])
    
    l = LABELS.get(biz.type, LABELS["generic"])
    
    w_l = {
        "barbershop": {"details": "Деталі візиту", "date": "Оберіть дату", "time": "Оберіть час", "btn": "Підтвердити запис"},
        "retail": {"details": "Що замовляємо?", "date": "Бажана дата отримання", "time": "Орієнтовний час", "btn": "Підтвердити замовлення"},
    }.get(biz.type, {"details": "Деталі візиту", "date": "Оберіть дату", "time": "Оберіть час", "btn": "Підтвердити запис"})
    
    icon_details = "fa-shopping-bag" if biz.type == 'retail' else "fa-cut"

    delivery_html = f"""
                <div class="glass-card animate-up" style="animation-delay: 0.75s;">
                    <h5 class="section-title"><i class="fas fa-truck text-primary opacity-75"></i> Доставка</h5>
                    <div class="mb-3"><input name="delivery_address" class="input-modern" required placeholder="Місто, № відділення пошти або адреса..."></div>
                </div>
    """ if biz.type == 'retail' else ""

    html_content = f"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"><title>Онлайн-запис | {html.escape(biz.name)}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{ 
            --accent-primary: #af85ff;
            --accent-pink: #f472b6;
            --bg: #000000;
            --glass-bg: rgba(255, 255, 255, 0.012);
            --glass-border: rgba(255, 255, 255, 0.08);
            --blur: 60px;
            --p: var(--accent-primary);
            --p-hover: #c084fc;
            --text: #ffffff; 
            --text-muted: rgba(255, 255, 255, 0.7); 
        }}
        body {{ 
            background: #000; 
            font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif; 
            color: var(--text); 
            -webkit-font-smoothing: antialiased; 
            padding-bottom: 2rem; 
            min-height: 100vh;
            letter-spacing: -0.02em;
            overflow-x: hidden;
            position: relative;
        }}
        body::before {{
            content: '';
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: 
                radial-gradient(circle at 10% 20%, rgba(175, 133, 255, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(244, 114, 182, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 50% 50%, rgba(96, 165, 250, 0.08) 0%, transparent 60%),
                radial-gradient(circle at 80% 10%, rgba(175, 133, 255, 0.05) 0%, transparent 30%);
            filter: blur(100px);
            z-index: -1;
            animation: meshMove 30s infinite alternate ease-in-out;
        }}
        @keyframes slideUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .animate-up {{ animation: slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards; opacity: 0; }}
        
        .header-block {{ 
            background: var(--glass-bg); 
            backdrop-filter: blur(var(--blur)) saturate(200%);
            -webkit-backdrop-filter: blur(var(--blur)) saturate(200%);
            padding: 2.5rem 1rem 2.5rem; 
            text-align: center; 
            border-bottom-left-radius: 40px; 
            border-bottom-right-radius: 40px; 
            border-bottom: 0.5px solid var(--glass-border);
            box-shadow: 0 20px 60px rgba(0,0,0,0.35); 
            margin-bottom: 2rem; 
            position: relative; 
        }}
        .header-block h3 {{ color: #ffffff !important; font-weight: 800; text-shadow: 0 0 15px rgba(255,255,255,0.2); }}
        .header-block p {{ color: #ffffff !important; opacity: 0.9 !important; font-weight: 600; letter-spacing: 0.02em; }}
        
        .avatar-wrapper {{ 
            width: 84px; 
            height: 84px; 
            background: linear-gradient(135deg, var(--p), #ec4899); 
            color: white !important; 
            border-radius: 28px; 
            display: inline-flex; 
            align-items: center; 
            justify-content: center; 
            font-size: 36px; 
            font-weight: 800; 
            box-shadow: 0 15px 30px rgba(139, 92, 241, 0.4); 
            margin-bottom: 1rem; 
            transform: rotate(-5deg); 
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
        }}
        .avatar-wrapper:hover {{ transform: rotate(0deg) scale(1.05); }}
        
        .booking-container {{ max-width: 500px; margin: auto; padding: 0 1rem; }}
        .glass-card {{ 
            background: var(--glass-bg); 
            backdrop-filter: blur(var(--blur)) saturate(200%);
            -webkit-backdrop-filter: blur(var(--blur)) saturate(200%);
            border: 0.5px solid var(--glass-border);
            border-radius: 32px; 
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.4), inset 0 0.5px 1px rgba(255, 255, 255, 0.15);
            padding: 1.5rem; 
            margin-bottom: 1.5rem; 
        }}
        
        .input-modern {{ 
            background: rgba(255, 255, 255, 0.02) !important;
            border: 0.5px solid var(--glass-border); 
            border-radius: 20px; 
            padding: 1.05rem 1.15rem; 
            width: 100%; 
            transition: all 0.3s; 
            font-weight: 600; 
            color: #ffffff !important; 
            appearance: none; 
            font-size: 1rem; 
            outline: none;
        }}
        .input-modern::placeholder {{ color: rgba(255, 255, 255, 0.45) !important; font-weight: 600; }}
        .input-modern:focus {{ 
            background: rgba(255, 255, 255, 0.04) !important;
            border-color: rgba(175, 133, 255, 0.4); 
            box-shadow: 0 0 30px rgba(175, 133, 255, 0.08), inset 0 1px 2px rgba(0,0,0,0.05); 
        }}
        
        .section-title {{ font-weight: 800; font-size: 1.1rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 8px; color: #ffffff !important; letter-spacing: -0.01em; }}
        
        .date-scroll {{ display: flex; gap: 0.75rem; overflow-x: auto; padding-bottom: 0.5rem; scrollbar-width: none; -ms-overflow-style: none; margin: 0 -0.5rem; padding: 0 0.5rem; }}
        .date-scroll::-webkit-scrollbar {{ display: none; }}
        .date-card {{ 
            flex: 0 0 calc(25% - 0.5rem); 
            min-width: 75px; 
            background: rgba(255,255,255,0.08); 
            border: 1px solid var(--glass-border); 
            border-radius: 24px; 
            padding: 1.2rem 0.5rem; 
            text-align: center; 
            cursor: pointer; 
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); 
            user-select: none; 
            display: flex; 
            flex-direction: column; 
            gap: 6px; 
            color: #ffffff;
        }}
        .date-card .day-name {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase; color: rgba(255, 255, 255, 0.9); }}
        .date-card .day-num {{ font-size: 1.4rem; font-weight: 800; color: #ffffff; letter-spacing: -0.02em; }}
        .date-card.active {{ 
            background: linear-gradient(135deg, var(--p), #ec4899); 
            border-color: transparent; 
            transform: translateY(-4px); 
            box-shadow: 0 12px 24px rgba(139, 92, 241, 0.4); 
        }}
        .date-card.active .day-name, .date-card.active .day-num {{ color: white !important; opacity: 1 !important; }}
        
        .time-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); gap: 0.75rem; }}
        .time-slot {{ 
            background: rgba(255,255,255,0.08); 
            border: 1px solid var(--glass-border); 
            border-radius: 16px; 
            padding: 1rem 0.5rem; 
            text-align: center; 
            cursor: pointer; 
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); 
            font-weight: 700; 
            color: #ffffff; 
            user-select: none; 
            font-size: 1rem; 
        }}
        .time-hint {{
            color: rgba(255, 255, 255, 0.9) !important;
            font-weight: 600;
            font-size: 0.95rem;
            letter-spacing: 0.02em;
        }}
        .time-slot.active {{ 
            background: linear-gradient(135deg, var(--p), #ec4899); 
            color: white !important; 
            border-color: transparent; 
            transform: scale(1.05); 
            box-shadow: 0 10px 20px rgba(139, 92, 241, 0.35); 
        }}
        
        .btn-super {{ 
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink)); 
            color: white !important; 
            border: none; 
            border-radius: 24px; 
            padding: 1.2rem; 
            font-size: 1.1rem; 
            font-weight: 800; 
            width: 100%; 
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
            box-shadow: 0 10px 30px rgba(175, 133, 255, 0.35); 
            letter-spacing: -0.01em; 
            margin-top: 1rem; 
        }}
        .btn-super:active {{ transform: scale(0.96); }}
        .btn-super:hover {{ transform: translateY(-3px); box-shadow: 0 15px 35px rgba(139, 92, 241, 0.6); }}
        
        .loader-overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: var(--bg); display: flex; justify-content: center; align-items: center; z-index: 9999; transition: opacity 0.5s ease; opacity: 1; pointer-events: none; }}
        .loader-overlay.hidden {{ opacity: 0; }}
        .spinner {{ width: 48px; height: 48px; border: 4px solid rgba(175, 133, 255, 0.18); border-left-color: var(--accent-primary); border-radius: 50%; animation: spin 1s linear infinite; }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        
        .toast-msg {{ position: fixed; top: 20px; left: 50%; transform: translateX(-50%) translateY(-100px); background: #22c55e; color: white; padding: 1rem 2rem; border-radius: 100px; font-weight: 600; box-shadow: 0 10px 30px rgba(34, 197, 94, 0.4); transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1); z-index: 10000; }}
        .toast-msg.show {{ transform: translateX(-50%) translateY(0); }}
        .toast-msg.error {{ background: #ef4444; box-shadow: 0 10px 30px rgba(239, 68, 68, 0.4); }}
        
        @media (max-width: 480px) {{ 
            .glass-card {{ border-radius: 24px; padding: 1.25rem; margin-bottom: 1rem; }}
            .header-block {{ padding: 2.5rem 1rem 1.5rem; border-bottom-left-radius: 32px; border-bottom-right-radius: 32px; margin-bottom: 1.5rem; }}
            .avatar-wrapper {{ width: 72px; height: 72px; font-size: 30px; border-radius: 22px; }}
        }}
    </style></head>
    <body>
        <div class="loader-overlay" id="loader"><div class="spinner"></div></div>
        <div class="toast-msg" id="toastMsg"></div>
        
        <div class="header-block">
            <div class="avatar-wrapper animate-up" style="animation-delay: 0.1s;">{(biz.name[0].upper() if biz.name else 'S')}</div>
            <h3 class="fw-bold mb-1 animate-up" style="animation-delay: 0.2s; letter-spacing: -0.03em;">{html.escape(biz.name)}</h3>
            <p class="animate-up mb-0" style="animation-delay: 0.3s;">Оберіть послугу та зручний час</p>
        </div>
        
        <div class="booking-container">
            <form action="/widget/book/{business_id}" method="post" id="bookingForm">
                <div class="glass-card animate-up" style="animation-delay: 0.4s;">
                    <h5 class="section-title"><i class="fas {icon_details} text-primary opacity-75"></i> {w_l['details']}</h5>
                    <div class="mb-3">
                        <select name="service" class="input-modern" required>
                            <option value="" disabled selected hidden>Оберіть {l['service_single'].lower()}...</option>
                            {s_opts}
                        </select>
                    </div>
                    <div>
                        <select name="master_id" class="input-modern">
                            <option value="">Будь-який {l['master_single'].lower()}</option>
                            {m_opts}
                        </select>
                    </div>
                </div>
                
                <div class="glass-card animate-up" style="animation-delay: 0.5s;">
                    <h5 class="section-title"><i class="fas fa-calendar-alt text-primary opacity-75"></i> {w_l['date']}</h5>
                    <div id="dateCards" class="date-scroll"></div>
                    <input type="hidden" name="date" id="selectedDate" required>
                </div>
                
                <div class="glass-card animate-up" style="animation-delay: 0.6s;">
                    <h5 class="section-title"><i class="fas fa-clock text-primary opacity-75"></i> {w_l['time']}</h5>
                    <div id="timeSlots" class="time-grid">
                        <div class="time-hint text-center w-100 py-3" style="grid-column: 1 / -1;">Спочатку оберіть дату</div>
                    </div>
                    <input type="hidden" name="time" id="selectedTime" required>
                </div>
                
                <div class="glass-card animate-up" style="animation-delay: 0.7s;">
                    <h5 class="section-title"><i class="fas fa-user text-primary opacity-75"></i> Ваші контакти</h5>
                    <div class="mb-3"><input name="name" class="input-modern" required placeholder="Ім'я"></div>
                    <div><input name="phone" type="tel" class="input-modern" required placeholder="+380..."></div>
                </div>
                
                {delivery_html}
                
                <div class="animate-up" style="animation-delay: 0.8s;">
                    <button type="submit" class="btn-super"><i class="fas fa-check-circle me-2"></i>{w_l['btn']}</button>
                </div> 
            </form>
        </div>
        
        <script>
            window.addEventListener('load', () => {{
                setTimeout(() => {{ document.getElementById('loader').classList.add('hidden'); }}, 200);
            }});

        const dateCardsContainer = document.getElementById('dateCards');
        const timeSlotsContainer = document.getElementById('timeSlots');
        const selectedDateInput = document.getElementById('selectedDate');
        const selectedTimeInput = document.getElementById('selectedTime');
        const daysOfWeek = ['Нд', 'Пн', 'Вв', 'Ср', 'Чт', 'Пт', 'Сб'];
        const today = new Date();

        function generateDates() {{
            let isRetail = {'true' if biz.type == 'retail' else 'false'}; 
            let startOffset = isRetail ? 1 : 0; // Для товарки мінімум завтрашній день
            for (let i = startOffset; i < 30 + startOffset; i++) {{
                let d = new Date();
                d.setDate(today.getDate() + i);
                
                let dayName = i === 0 ? 'Сьог' : (i === 1 ? 'Зав' : daysOfWeek[d.getDay()]);
                let dayNum = d.getDate();
                let monthNum = String(d.getMonth() + 1).padStart(2, '0'); 
                let yearNum = d.getFullYear();
                let dateString = `${{yearNum}}-${{monthNum}}-${{String(dayNum).padStart(2, '0')}}`;
                
                let card = document.createElement('div');
                card.className = 'date-card';
                card.innerHTML = `<div class="day-name">${{dayName}}</div><div class="day-num">${{dayNum}}</div>`;
                card.onclick = () => selectDate(card, dateString);
                dateCardsContainer.appendChild(card);
            }}
        }}

        function selectDate(element, dateStr) {{
            document.querySelectorAll('.date-card').forEach(el => el.classList.remove('active')); 
            element.classList.add('active');
            selectedDateInput.value = dateStr;
            generateTimes();
        }}

        function generateTimes() {{
            timeSlotsContainer.innerHTML = '';
            selectedTimeInput.value = '';
            const startHour = 9;
            const endHour = 19; 
            
            for(let h = startHour; h <= endHour; h++) {{
                for(let m of ['00', '30']) {{
                    let timeStr = `${{String(h).padStart(2, '0')}}:${{m}}`;
                    let btn = document.createElement('div');
                    btn.className = 'time-slot';
                    btn.innerText = timeStr;
                    btn.onclick = () => selectTime(btn, timeStr);
                    timeSlotsContainer.appendChild(btn);
                }}
            }}
        }}
        
        function selectTime(element, timeStr) {{
            document.querySelectorAll('.time-slot').forEach(el => el.classList.remove('active'));
            element.classList.add('active');
            selectedTimeInput.value = timeStr;
        }}

            function showToast(msg, isError = false) {{
                const toast = document.getElementById('toastMsg'); 
                toast.innerText = msg;
                if(isError) toast.classList.add('error');
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show', 'error'), 4000);
            }}

        generateDates();

        document.getElementById('bookingForm').addEventListener('submit', function(e) {{
            if(!selectedDateInput.value || !selectedTimeInput.value) {{ 
                e.preventDefault();
                    showToast('Будь ласка, оберіть дату та час візиту!', true);
            }}
        }});

        const urlParams = new URLSearchParams(window.location.search);
            if(urlParams.get('msg') === 'success') showToast('✅ Ваш запис успішно створено! Чекаємо на вас.');
            if(urlParams.get('msg') === 'taken') showToast('⚠️ На жаль, цей час вже зайнятий. Оберіть інший.', true); 
        </script>
    </body></html>"""
    return HTMLResponse(content=html_content)


@router.post("/book/{business_id}")
async def process_public_booking(
    business_id: int,
    phone: str = Form(...),
    name: str = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    service: str = Form(...),
    master_id: str = Form(None),
    delivery_address: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    srv = (await db.execute(select(Service).where(and_(Service.name == service, Service.business_id == business_id)))).scalar_one_or_none()
    duration = srv.duration if srv and srv.duration else 90
    cost = srv.price if srv else 0.0
    
    new_start = dt
    new_end = dt + timedelta(minutes=duration)
    
    stmt_overlap = select(Appointment).where(and_(Appointment.business_id == business_id, Appointment.status != 'cancelled', Appointment.appointment_time >= day_start, Appointment.appointment_time < day_end))
    existing_apps = (await db.execute(stmt_overlap)).scalars().all()
    
    for app in existing_apps:
        app_dur = 90
        s_ex = (await db.execute(select(Service).where(and_(Service.name == app.service_type, Service.business_id == business_id)))).scalar_one_or_none()
        if s_ex and s_ex.duration: app_dur = s_ex.duration
        app_end = app.appointment_time + timedelta(minutes=app_dur)
        
        if new_start < app_end and new_end > app.appointment_time:
            return RedirectResponse(f"/widget/{business_id}?msg=taken", status_code=303)
    
    cust = (await db.execute(select(Customer).where(and_(Customer.phone_number == phone, Customer.business_id == business_id)))).scalar_one_or_none()
    if not cust:
        cust = Customer(business_id=business_id, phone_number=phone, name=name)
        db.add(cust); await db.flush()
    
    app = Appointment(business_id=business_id, customer_id=cust.id, appointment_time=dt, service_type=service, cost=cost, delivery_address=delivery_address, source="widget", master_id=int(master_id) if master_id else None)
    db.add(app)
    await db.commit()
    
    biz = await db.get(Business, business_id)
    await send_new_appointment_notifications(biz, app, db)
    
    active_ints = biz.integration_system.split(',') if biz.integration_system else []
    
    if "beauty_pro" in active_ints and biz.beauty_pro_token and biz.beauty_pro_location_id:
        result = await push_to_beauty_pro({
            "phone": phone, "name": name, "service": service, 
            "datetime": dt.isoformat(), "cost": cost
        }, biz.beauty_pro_token, biz.beauty_pro_location_id, biz.beauty_pro_api_url)
        if result:
            await log_action(db, business_id, None, "Синхронізація CRM (Beauty Pro)", f"Віджет: {result.get('msg', '')}")
            
    if "cleverbox" in active_ints and biz.cleverbox_token:
        result = await push_to_cleverbox({
            "phone": phone, "name": name, "service": service, 
            "datetime": dt.isoformat(), "cost": cost
        }, biz.cleverbox_token, biz.cleverbox_location_id, biz.cleverbox_api_url)
        if result:
            await log_action(db, business_id, None, "Синхронізація CRM (Cleverbox)", f"Віджет: {result.get('msg', '')}")
            
    if "integrica" in active_ints and biz.integrica_token:
        result = await push_to_integrica({
            "phone": phone, "name": name, "service": service, 
            "datetime": dt.isoformat(), "cost": cost
        }, biz.integrica_token, biz.integrica_location_id, biz.integrica_api_url)
        if result:
            await log_action(db, business_id, None, "Синхронізація CRM (Integrica)", f"Віджет: {result.get('msg', '')}")
            
    if "luckyfit" in active_ints and biz.luckyfit_token:
        result = await push_to_luckyfit({
            "phone": phone, "name": name, "service": service, 
            "datetime": dt.isoformat(), "cost": cost
        }, biz.luckyfit_token)
        if result:
            await log_action(db, business_id, None, "Синхронізація CRM (LuckyFit)", f"Віджет: {result.get('msg', '')}")

    if "uspacy" in active_ints and biz.uspacy_token and biz.uspacy_workspace_id:
        result = await push_to_uspacy({
            "phone": phone, "name": name, "service": service, 
            "datetime": dt.isoformat(), "cost": cost
        }, biz.uspacy_token, biz.uspacy_workspace_id)
        if result:
            await log_action(db, business_id, None, "Синхронізація CRM (uSpacy)", f"Віджет: {result.get('msg', '')}")

    await db.commit()
    
    return RedirectResponse(f"/widget/{business_id}?msg=success", status_code=303)
    """Get services for widget"""
    services = (await db.execute(
        select(Service).where(Service.business_id == business_id)
    )).scalars().all()
    return {"services": [{"id": s.id, "name": s.name, "price": s.price} for s in services]}


@router.post("/api/chat")
async def widget_chat_api(data: dict, db: AsyncSession = Depends(get_db)):
    """Handle widget chat messages"""
    try:
        business_id = data.get('business_id')
        message = data.get('message', '')
        session_id = data.get('session_id', 'unknown')

        biz = await db.get(Business, business_id)
        if not biz:
            return {"response": "Бізнес не знайдено"}

        # Simple intent detection
        msg_lower = message.lower()
        if any(w in msg_lower for w in ['запис', 'записатись', 'бронювання', 'booking']):
            return {"response": "З радістю допоможу вам зареєструвати візит! Оберіть сервіс та зручний час.", "action": "booking"}

        if any(w in msg_lower for w in ['ціна', 'вартість', 'скільки', 'price', 'cost']):
            services = (await db.execute(
                select(Service).where(Service.business_id == business_id).limit(5)
            )).scalars().all()
            svcs = ", ".join([f"{s.name} - {s.price} грн" for s in services])
            return {"response": f"Наші сервіси: {svcs}. Бажаєте зареєструвати візит на один із них?"}

        if any(w in msg_lower for w in ['графік', 'час', 'коли', 'hours', 'time']):
            return {"response": f"Ми працюємо: {biz.working_hours or 'Пн-Пт: 09:00 - 20:00'}. Коли вам було б зручно завітати?"}

        # Default AI response (Simplified for now, real AI would use Groq)
        return {"response": f"Дякуємо за ваше повідомлення: '{message}'. Наш менеджер скоро зв'яжеться з вами або ви можете скористатись кнопкою онлайн-запису."}

    except Exception as e:
        logger.error(f"Widget chat error: {e}")
        return {"response": "Вибачте, виникла помилка. Спробуйте пізніше."}


@router.post("/api/book")
async def widget_book_api(data: dict, db: AsyncSession = Depends(get_db)):
    """Handle widget booking"""
    try:
        business_id = data.get('business_id')
        service_id = int(data.get('service_id', 0))
        date_str = data.get('date')
        phone = data.get('phone', '').strip()

        if not phone or not date_str:
            return {"success": False, "error": "Будь ласка, вкажіть телефон та дату."}

        # Get or create customer
        customer = await db.scalar(
            select(Customer).where(and_(Customer.business_id == business_id, Customer.phone_number == phone))
        )
        if not customer:
            customer = Customer(business_id=business_id, phone_number=phone, name="Клієнт з віджета")
            db.add(customer)
            await db.commit()
            await db.refresh(customer)

        # Get service and master
        service = await db.get(Service, service_id)
        if not service:
            return {"success": False, "error": "Послугу не знайдено"}

        # Find available master
        master = await db.scalar(
            select(Master).where(Master.business_id == business_id).limit(1)
        )

        # Parse date and create appointment
        appt_time = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=14, minute=0)

        appt = Appointment(
            business_id=business_id,
            customer_id=customer.id,
            master_id=master.id if master else None,
            appointment_time=appt_time,
            service_type=service.name,
            cost=service.price,
            source="widget",
            status="confirmed"
        )
        db.add(appt)
        await db.commit()

        # Send notification to business owner if configured
        biz = await db.get(Business, business_id)
        if biz.telegram_notifications_enabled and biz.telegram_notification_chat_id and biz.telegram_token:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{biz.telegram_token}/sendMessage",
                    json={
                        "chat_id": biz.telegram_notification_chat_id,
                        "text": f"🔔 Новий запис з сайту!\n📞 Тел: {phone}\n🛠 Послуга: {service.name}\n📅 Час: {appt_time.strftime('%d.%m %H:%M')}"
                    }
                )

        return {
            "success": True,
            "time": appt_time.strftime("%d.%m.%Y %H:%M"),
            "master": master.name if master else "Адміністратор"
        }

    except Exception as e:
        logger.error(f"Widget booking error: {e}")
        return {"success": False, "error": "Помилка при створенні запису."}
