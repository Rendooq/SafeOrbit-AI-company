import html
import os
import shutil
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from config import SUPERADMIN_TG_BOT_TOKEN, SUPERADMIN_TG_CHAT_ID
from database import get_db
from models import Business, GlobalPaymentSettings, User
from utils import hash_password, verify_password

router = APIRouter(tags=["Authentication"])


@router.get("/register", response_class=HTMLResponse)
async def register_page(db: AsyncSession = Depends(get_db)):
    # Load global payment settings
    settings = await db.scalar(select(GlobalPaymentSettings).where(GlobalPaymentSettings.id == 1))
    if not settings:
        settings = GlobalPaymentSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    iban = settings.iban or "UA363220010000026205345692520"
    bank_name = settings.bank_name or "Monobank"
    receiver = settings.receiver_name or "SafeOrbit"
    qr_url = settings.qr_url or "/static/payment_qr.png"

    return f"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Реєстрація | SafeOrbit</title>
    <link rel="icon" href="/static/favicon.png" type="image/png">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
    :root {{
        --bg-primary: #000000;
        --accent-primary: #BB86FC; /* Softer, slightly brighter purple */
        --accent-pink: #FFC0CB; /* Soft pink for gradients */
        --glass-bg: rgba(25, 12, 45, 0.3); /* Lighter, more transparent */
        --glass-border: rgba(187, 134, 252, 0.3); /* Matches accent-primary */
        --blur: 40px; /* Consistent blur value */
    }}
    body {{ 
        background: #000; 
        font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif; 
        min-height: 100vh; 
        display: flex; 
        align-items: center; 
        justify-content: center; 
        margin: 0; 
        padding: 80px 20px; 
        color: #ffffff; 
        overflow-x: hidden;
        position: relative;
    }}
    
    /* iOS 26 Mesh Background */
    body::before {{
        content: '';
        position: fixed;
        top: 0; left: 0; width: 100%; height: 100%;
        background: 
            radial-gradient(circle at 15% 0%, rgba(187, 134, 252, 0.25) 0%, transparent 60%),
            radial-gradient(circle at 85% 100%, rgba(255, 192, 203, 0.15) 0%, transparent 50%),
            radial-gradient(circle at 50% 50%, rgba(12, 5, 26, 1) 0%, transparent 100%);
        filter: blur(80px); /* Adjust blur for better blend */
        z-index: -1;
        animation: meshMove 30s infinite alternate ease-in-out;
    }}

    @keyframes meshMove {{
        0% {{ transform: translate(0, 0) scale(1); }}
        33% {{ transform: translate(4%, 4%) scale(1.15); }}
        66% {{ transform: translate(-2%, 5%) scale(0.9); }}
        100% {{ transform: translate(0, 0) scale(1); }}
    }}

    .register-card {{ 
        background: var(--glass-bg);
        backdrop-filter: blur(var(--blur)) saturate(200%);
        -webkit-backdrop-filter: blur(var(--blur)) saturate(200%);
        padding: 4rem 3rem; /* Slightly reduced padding */
        border-radius: 48px;
        border: 0.5px solid var(--glass-border);
        box-shadow: 0 50px 120px rgba(0,0,0,0.6), inset 0 0.5px 1px rgba(255,255,255,0.2);
        width: 100%;
        max-width: 780px;
        animation: fadeIn 1.2s cubic-bezier(0.16, 1, 0.3, 1);
    }}

    @keyframes fadeIn {{
        from {{ opacity: 0; transform: translateY(30px) scale(0.98); }}
        to {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}

    .logo-box {{
        width: 80px;
        height: 80px;
        background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink));
        border-radius: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 36px;
        margin: 0 auto 32px;
        box-shadow: 0 20px 40px rgba(187, 134, 252, 0.35); /* Updated shadow */
        transform: rotate(-5deg);
    }}

    .form-label {{
        color: rgba(255, 255, 255, 0.6);
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 12px;
        display: block;
        padding-left: 6px;
    }}

    .form-control, .form-select {{ 
        background: rgba(255, 255, 255, 0.01) !important; 
        border: 0.5px solid var(--glass-border) !important; 
        border-radius: 22px !important; 
        padding: 1.1rem 1.4rem !important; 
        color: white !important; 
        font-weight: 500 !important;
        font-size: 16px !important;
        transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.2) !important;
    }}

    .form-control:focus, .form-select:focus {{ 
        background: rgba(255, 255, 255, 0.035) !important;
        border-color: rgba(187, 134, 252, 0.5) !important; /* Updated border focus */
        box-shadow: 0 0 40px rgba(187, 134, 252, 0.15), inset 0 1px 2px rgba(0,0,0,0.1) !important; /* Updated shadow */
        transform: translateY(-2px);
    }}

    .plan-card {{
        background: rgba(255, 255, 255, 0.015);
        border: 0.5px solid var(--glass-border);
        border-radius: 24px; /* Slightly less rounded */
        padding: 24px; /* Reduced padding */
        cursor: pointer;
        transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
        position: relative;
        overflow: hidden;
        height: 100%;
    }}

    .btn-check:checked + .plan-card {{
        background: rgba(175, 133, 255, 0.05);
        border-color: var(--accent-primary); /* Keep primary accent */
        box-shadow: 0 25px 50px rgba(187, 134, 252, 0.2); /* Updated shadow */
        transform: translateY(-4px) scale(1.03);
    }}

    .plan-card.disabled {{
        opacity: 0.2;
        cursor: not-allowed;
        filter: grayscale(1);
    }}

    .plan-price {{
        font-size: 26px;
        font-weight: 800;
        color: #ffffff;
        letter-spacing: -1px;
    }}

    .plan-desc {{
        font-size: 14px;
        color: rgba(255, 255, 255, 0.45);
        font-weight: 500;
        margin-top: 6px;
    }}

    .section-divider {{
        height: 0.5px;
        background: var(--glass-border);
        margin: 50px 0;
    }}

    .doc-box {{
        background: rgba(175, 133, 255, 0.02);
        border: 0.5px solid rgba(175, 133, 255, 0.1);
        border-radius: 32px;
        padding: 40px;
    }}

    .payment-alert {{
        background: rgba(255, 255, 255, 0.01);
        border: 0.5px solid var(--glass-border);
        border-radius: 32px;
        padding: 40px;
        text-align: center;
    }}

    .btn-primary-glow {{
        background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink));
        border: none;
        color: white !important;
        padding: 1.2rem !important;
        border-radius: 18px !important; /* Slightly less rounded */
        font-weight: 800 !important;
        font-size: 18px !important;
        box-shadow: 0 20px 40px rgba(175, 133, 255, 0.35);
        transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1) !important;
    }} 

    .btn-primary-glow:hover:not(:disabled) {{
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 30px 60px rgba(175, 133, 255, 0.5);
    }}

    .btn-secondary-glass {{
        background: rgba(255, 255, 255, 0.025);
        border: 0.5px solid var(--glass-border);
        color: white;
        padding: 12px 20px; /* Slightly reduced */
        border-radius: 18px;
        font-weight: 600;
        font-size: 14px;
        transition: all 0.4s;
        text-decoration: none !important;
    }}

    .btn-secondary-glass:hover {{
        background: rgba(255, 255, 255, 0.06);
        border-color: rgba(255, 255, 255, 0.2);
        transform: translateY(-2px);
    }}

    .badge-status {{
        font-size: 11px;
        padding: 6px 12px;
        border-radius: 10px;
        background: rgba(248, 113, 113, 0.1);
        color: #f87171;
        font-weight: 800;
        text-transform: uppercase;
        margin-top: 15px;
        display: inline-block;
        letter-spacing: 0.5px;
    }}
    </style></head>
    <body>
    <div class="register-card">
        <div class="logo-box"><i class="fas fa-bolt"></i></div>
        <div class="text-center mb-5">
            <h2 class="fw-800 text-white mb-2" style="font-size: 38px; letter-spacing: -1.5px;">Реєстрація</h2>
            <p style="color: rgba(255, 255, 255, 0.4); font-weight: 500; font-size: 17px;">Почніть свій шлях з SafeOrbit</p>
        </div>
        
        <form action="/register" method="post" enctype="multipart/form-data">
            <div class="row g-4">
                <div class="col-12">
                    <label class="form-label">Назва бізнесу</label>
                    <input name="name" class="form-control" placeholder="Введіть назву..." required>
                </div>
                
                <div class="col-md-6">
                    <label class="form-label">Сфера діяльності</label>
                    <select name="type" class="form-select" onchange="document.getElementById('retailCatDiv').style.display = this.value === 'retail' ? 'block' : 'none';">
                        <option value="barbershop">Салон краси / Барбершоп</option>
                        <option value="dentistry">Стоматологія</option>
                        <option value="medical">Медичний центр</option>
                        <option value="fitness">Фітнес / Спорт</option>
                        <option value="retail">Магазин / Товарний бізнес</option>
                        <option value="generic">Інше</option>
                    </select>
                </div>

                <div class="col-md-6" id="retailCatDiv" style="display:none;">
                    <label class="form-label">Категорія товарів</label>
                    <select name="retail_subcategory" class="form-select">
                        <option value="clothing">👕 Одяг та взуття</option>
                        <option value="electronics">💻 Електроніка</option>
                        <option value="cosmetics">💄 Косметика</option>
                        <option value="home">🏡 Дім та сад</option>
                        <option value="kids">🧸 Дитячі товари</option>
                        <option value="sports">⚽ Спорт</option>
                        <option value="auto">🚗 Автотовари</option>
                    </select>
                </div>
                
                <div class="col-md-6">
                    <label class="form-label">Телефон (ваш логін)</label>
                    <input name="phone" type="tel" class="form-control" placeholder="+380..." required>
                </div>
                
                <div class="col-md-6">
                    <label class="form-label">Пароль</label>
                    <input name="password" type="password" class="form-control" placeholder="••••••••" required>
                </div>
            </div>

            <div class="section-divider"></div>

            <div class="mb-5">
                <label class="form-label mb-4">Оберіть тарифний план</label>
                <div class="row g-4">
                    <div class="col-6">
                        <input type="radio" class="btn-check" name="plan_type" id="plan1" value="plan1" {"checked" if settings.is_plan1_active else "disabled"} onchange="updatePlan()">
                        <label class="plan-card {'disabled' if not settings.is_plan1_active else ''}" for="plan1">
                            <div class="plan-price">11 000 ₴<small style="font-size: 15px; opacity: 0.5;">/міс</small></div>
                            <div class="plan-desc">+ 9 000 ₴ налаштування</div>
                            {f'<span class="badge-status">Тимчасово недоступний</span>' if not settings.is_plan1_active else ''}
                        </label>
                    </div>
                    <div class="col-6">
                        <input type="radio" class="btn-check" name="plan_type" id="plan2" value="plan2" {"checked" if not settings.is_plan1_active and settings.is_plan2_active else "disabled" if not settings.is_plan2_active else ""} onchange="updatePlan()">
                        <label class="plan-card {'disabled' if not settings.is_plan2_active else ''}" for="plan2">
                            <div class="plan-price">53 000 ₴</div>
                            <div class="plan-desc">+ 1 100 ₴/міс тех.підтримка</div>
                            {f'<span class="badge-status">Тимчасово недоступний</span>' if not settings.is_plan2_active else ''}
                        </label>
                    </div>
                </div>
            </div>

            <div class="doc-box mb-5">
                <h6 class="text-white fw-800 mb-4"><i class="fas fa-file-shield me-2" style="color: var(--accent-primary);"></i>Документи</h6>
                <div class="d-flex gap-3 mb-4">
                    <a href="/static/nda.pdf" target="_blank" class="btn-secondary-glass flex-grow-1 text-center"><i class="fas fa-download me-2"></i>NDA.pdf</a>
                    <a href="/static/contract_plan1.pdf" target="_blank" id="contractTemplateLink" class="btn-secondary-glass flex-grow-1 text-center"><i class="fas fa-download me-2"></i>Договір.pdf</a>
                </div>
                <div class="row g-4">
                    <div class="col-md-6">
                        <label class="form-label">Підписаний NDA</label>
                        <input type="file" name="nda_file" class="form-control" accept=".pdf,image/*" required>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Підписаний Договір</label>
                        <input type="file" name="contract_file" class="form-control" accept=".pdf,image/*" required>
                    </div>
                </div>
            </div>

            <div class="payment-alert mb-5">
                <h6 class="fw-800 mb-4 text-warning"><i class="fas fa-wallet me-2"></i>Оплата підписки</h6>
                <div id="paymentAmountText" class="fs-4 fw-800 mb-4 text-white">До сплати: 20 000 ₴</div>
                
                <div class="d-flex justify-content-center gap-3 mb-4">
                    <button type="button" class="btn-secondary-glass active" id="btnIban" onclick="showPayment('iban')">IBAN реквізити</button>
                    <button type="button" class="btn-secondary-glass" id="btnQr" onclick="showPayment('qr')">QR-код</button>
                </div>
                
                <div id="payIban" class="p-4 rounded-4 mb-4" style="background: rgba(255,255,255,0.015); border: 0.5px solid var(--glass-border); cursor: pointer;" onclick="copyIban()">
                    <div id="ibanText" class="fw-800 fs-5 mb-3 text-white" style="letter-spacing: 1px;">{iban}</div>
                    <div class="d-flex justify-content-center align-items-center gap-3">
                        <span id="ibanBadge" class="badge bg-primary bg-opacity-10 text-primary px-3 py-2" style="border: 0.5px solid rgba(96, 165, 250, 0.2);">{bank_name}</span>
                        <span class="small opacity-40 fw-600"><i class="fas fa-copy me-1"></i>Натисніть для копіювання</span>
                    </div>
                    {f'<div class="small opacity-30 mt-3 fw-500">Отримувач: {receiver}</div>' if receiver else ''}
                </div>
                
                <div id="payQr" class="mb-4 text-center" style="display:none;">
                    <img src="{qr_url}" alt="QR" class="img-fluid rounded-4" style="max-width: 260px; box-shadow: 0 30px 60px rgba(0,0,0,0.4);" onerror="this.style.display='none'; document.getElementById('qrFallback').style.display='block';">
                    <div id="qrFallback" class="opacity-20 py-5" style="display:none;"><i class="fas fa-qrcode fa-5x"></i><p class="mt-3">QR-код не налаштовано</p></div>
                </div>
                
                <div class="text-start">
                    <label class="form-label">Чек про оплату</label>
                    <input type="file" name="receipt" class="form-control" accept="image/*" required onchange="previewReceipt(event)">
                    <img id="receiptPreview" src="#" alt="Preview" class="img-fluid rounded-4 mt-4" style="display:none; max-height: 250px; margin: 0 auto; box-shadow: 0 20px 40px rgba(0,0,0,0.5);">
                </div>
            </div>
            
            <div class="form-check mb-5 px-4">
                <input class="form-check-input" type="checkbox" id="privacyPolicy" onchange="document.getElementById('submitBtn').disabled = !this.checked;" style="background-color: rgba(255,255,255,0.02); border-color: var(--glass-border);">
                <label class="form-check-label small opacity-40 ms-2 fw-500" for="privacyPolicy">
                    Я погоджуюся з умовами використання та обробкою персональних даних
                </label>
            </div>
            
            <button id="submitBtn" class="btn-primary-glow w-100 mb-5" disabled>Створити бізнес-акаунт</button>
            
            <div class="text-center">
                <a href="/" class="text-link">Вже є акаунт? <span style="color: #ffffff;">Увійти</span></a>
            </div>
        </form>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
    function showPayment(type) {{
        const isIban = type === 'iban';
        document.getElementById('payIban').style.display = isIban ? 'block' : 'none';
        document.getElementById('payQr').style.display = isIban ? 'none' : 'block';
        document.getElementById('btnIban').classList.toggle('active', isIban);
        document.getElementById('btnQr').classList.toggle('active', !isIban);
    }}
    function copyIban() {{
        const iban = document.getElementById('ibanText').innerText;
        navigator.clipboard.writeText(iban).then(() => {{
            const badge = document.getElementById('ibanBadge');
            const old = badge.innerHTML;
            badge.innerHTML = '<i class="fas fa-check me-2"></i>Скопійовано!';
            badge.classList.replace('text-primary', 'text-success');
            badge.style.borderColor = 'rgba(52, 211, 153, 0.4)';
            setTimeout(() => {{ 
                badge.innerHTML = old; 
                badge.classList.replace('text-success', 'text-primary');
                badge.style.borderColor = '';
            }}, 2000);
        }});
    }}
    function previewReceipt(event) {{
        const reader = new FileReader();
        reader.onload = function() {{ 
            const output = document.getElementById('receiptPreview'); 
            output.src = reader.result; 
            output.style.display = 'block'; 
        }}
        reader.readAsDataURL(event.target.files[0]);
    }}
    function updatePlan() {{
        const p1 = document.getElementById('plan1').checked;
        const link = document.getElementById('contractTemplateLink');
        const priceText = document.getElementById('paymentAmountText');
        if (p1) {{
            link.href = '/static/contract_plan1.pdf';
            priceText.innerHTML = "До сплати: <b class='text-white'>20 000 ₴</b> <span class='small opacity-40 fw-500'>(11.000 + 9.000)</span>";
        }} else {{
            link.href = '/static/contract_plan2.pdf';
            priceText.innerHTML = "До сплати: <b class='text-white'>54 100 ₴</b> <span class='small opacity-40 fw-500'>(53.000 + 1.100)</span>";
        }}
    }}
    document.addEventListener('DOMContentLoaded', () => {{
        updatePlan();
        showPayment('iban');
    }});
    </script>
    </body></html>"""


@router.post("/register")
async def register_post(name: str = Form(...), phone: str = Form(...), password: str = Form(...), type: str = Form(...), retail_subcategory: str = Form(None), plan_type: str = Form("plan1"), receipt: UploadFile = File(...), nda_file: UploadFile = File(...), contract_file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(User).where(User.username == phone))).scalar_one_or_none()
    if existing: return HTMLResponse("Цей номер вже зареєстровано. Поверніться назад.", status_code=400)
    
    os.makedirs("static/uploads/receipts", exist_ok=True)
    os.makedirs("static/uploads/documents", exist_ok=True)
    
    ext = receipt.filename.split('.')[-1] if '.' in receipt.filename else 'jpg'
    f_receipt = f"static/uploads/receipts/receipt_{int(datetime.now().timestamp())}.{ext}"
    with open(f_receipt, "wb") as buffer: shutil.copyfileobj(receipt.file, buffer)
    
    f_nda = f"static/uploads/documents/nda_{int(datetime.now().timestamp())}.{nda_file.filename.split('.')[-1]}"
    with open(f_nda, "wb") as buffer: shutil.copyfileobj(nda_file.file, buffer)
        
    f_contract = f"static/uploads/documents/contract_{int(datetime.now().timestamp())}.{contract_file.filename.split('.')[-1]}"
    with open(f_contract, "wb") as buffer: shutil.copyfileobj(contract_file.file, buffer)
        
    nb = Business(name=name, type=type, retail_subcategory=retail_subcategory if type == 'retail' else None, plan_type=plan_type, contract_url=f"/{f_contract}", nda_url=f"/{f_nda}", is_active=False, payment_status="pending", receipt_url=f"/{f_receipt}")
    db.add(nb); await db.commit(); await db.refresh(nb)
    nu = User(username=phone, password=hash_password(password), role="owner", business_id=nb.id)
    db.add(nu); await db.commit()
    
    superadmin = (await db.execute(select(User).where(User.role == 'superadmin'))).scalars().first()
    bot_token = superadmin.tg_bot_token if superadmin and getattr(superadmin, 'tg_bot_token', None) else SUPERADMIN_TG_BOT_TOKEN
    chat_id = superadmin.tg_chat_id if superadmin and getattr(superadmin, 'tg_chat_id', None) else SUPERADMIN_TG_CHAT_ID

    if bot_token and chat_id:
        if plan_type == "plan1":
            msg = f"🆕 Нова заявка на підключення!\nБізнес: {name}\nТелефон: {phone}\nТариф: Базовий (11 000 грн/міс)"
        else:
            msg = f"🚀 🔥 УВАГА! НОВА VIP ЗАЯВКА!\nБізнес: {name}\nТелефон: {phone}\nТариф: PRO (53 000 грн + 1 100 грн/міс) 💰\nОчікує перевірки!"
        try:
            async with httpx.AsyncClient() as client_tg:
                await client_tg.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": msg})
        except Exception as e:
            # In a real app, you'd have proper logging here
            print(f"Superadmin TG Notify Error: {e}")
            
    return RedirectResponse(f"/pending-activation/{nb.id}", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def login_page():
    return """<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Вхід | SafeOrbit</title>
    <link rel="icon" href="/static/favicon.png" type="image/png">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
    :root {
        --bg-primary: #000000;
        --accent-primary: #af85ff;
        --accent-pink: #FFC0CB; /* Soft pink for gradients */
        --glass-bg: rgba(255, 255, 255, 0.012);
        --glass-border: rgba(255, 255, 255, 0.08);
        --blur: 60px;
    }
    body { 
        background: #000;
        font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0;
        color: #ffffff;
        overflow: hidden;
        position: relative;
    }
    
    /* iOS 26 Mesh Background */
    body::before {
        content: '';
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: 
            radial-gradient(circle at 15% 0%, rgba(187, 134, 252, 0.25) 0%, transparent 60%),
            radial-gradient(circle at 85% 100%, rgba(255, 192, 203, 0.15) 0%, transparent 50%),
            radial-gradient(circle at 50% 50%, rgba(12, 5, 26, 1) 0%, transparent 100%);
        filter: blur(100px);
        z-index: -1;
        animation: meshMove 30s infinite alternate ease-in-out;
    }

    @keyframes meshMove {
        0% { transform: translate(0, 0) scale(1); }
        33% { transform: translate(4%, 4%) scale(1.15); }
        66% { transform: translate(-2%, 5%) scale(0.9); }
        100% { transform: translate(0, 0) scale(1); }
    }

    .login-container {
        width: 100%;
        max-width: 480px;
        padding: 24px;
        position: relative;
        z-index: 1;
        animation: fadeIn 1.2s cubic-bezier(0.16, 1, 0.3, 1);
    }

    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(30px) scale(0.95); }
        to { opacity: 1; transform: translateY(0) scale(1); }
    }

    .login-card { 
        background: var(--glass-bg);
        backdrop-filter: blur(var(--blur)) saturate(200%);
        -webkit-backdrop-filter: blur(var(--blur)) saturate(200%);
        padding: 3.5rem 2.5rem; /* Reduced padding for more compact look */
        border-radius: 48px;
        border: 0.5px solid var(--glass-border);
        box-shadow: 0 50px 120px rgba(0,0,0,0.6), inset 0 0.5px 1px rgba(255,255,255,0.2);
        text-align: center;
    }

    .logo-circle { 
        width: 88px;
        height: 88px;
        background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink));
        border-radius: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 42px;
        margin-bottom: 2.5rem;
        box-shadow: 0 25px 50px rgba(187, 134, 252, 0.35); /* Updated shadow */
        color: white;
        transform: rotate(-8deg);
        animation: logoFloat 8s ease-in-out infinite;
    }

    @keyframes logoFloat {
        0%, 100% { transform: rotate(-8deg) translateY(0); }
        50% { transform: rotate(-4deg) translateY(-15px); }
    }

    .form-control { 
        background: rgba(255, 255, 255, 0.01) !important; 
        border: 0.5px solid var(--glass-border) !important; 
        border-radius: 22px !important; 
        padding: 1.2rem 1.5rem !important; 
        color: white !important; 
        font-weight: 500 !important;
        font-size: 16px !important;
        transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.2) !important;
    }

    .form-control:focus { 
        background: rgba(255, 255, 255, 0.035) !important;
        border-color: rgba(187, 134, 252, 0.5) !important; /* Updated border focus */
        box-shadow: 0 0 40px rgba(187, 134, 252, 0.15), inset 0 1px 2px rgba(0,0,0,0.1) !important; /* Updated shadow */
        transform: translateY(-2px);
    }

    .form-label { 
        color: rgba(255, 255, 255, 0.6);
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 12px;
        padding-left: 6px;
        text-align: left;
        display: block;
    }

    .btn-primary { 
        background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink)) !important; 
        border: none !important; 
        border-radius: 18px !important; /* Slightly less rounded */
        padding: 1.1rem !important; /* Slightly smaller padding */
        font-weight: 800 !important; 
        box-shadow: 0 20px 40px rgba(175, 133, 255, 0.35) !important; 
        color: white !important;
        font-size: 17px !important;
        transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1) !important;
        width: 100%;
    }

    .btn-primary:hover {
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 30px 60px rgba(175, 133, 255, 0.5) !important;
    }

    .btn-demo {
        background: rgba(255, 255, 255, 0.02) !important;
        border: 0.5px solid var(--glass-border) !important;
        border-radius: 18px !important; /* Slightly less rounded */
        padding: 1.2rem !important;
        color: #fff !important;
        font-weight: 700 !important;
        font-size: 16px !important;
        transition: all 0.5s !important;
        width: 100%;
        margin-top: 1.2rem;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        text-decoration: none;
    }

    .btn-demo:hover {
        background: rgba(255, 255, 255, 0.06) !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
        transform: translateY(-3px);
    }

    .text-link { 
        color: rgba(255, 255, 255, 0.45); 
        text-decoration: none; 
        font-weight: 600; 
        font-size: 15px;
        transition: 0.3s; 
    }
    .text-link:hover { color: #ffffff; }

    @media (max-width: 480px) {{ 
        .login-card {{ padding: 3.5rem 2rem; border-radius: 40px; }}
    }}
    </style></head>
    <body>
    <div class="login-container">
        <div class="login-card">
            <div class="logo-circle"><i class="fas fa-bolt"></i></div>
            <h2 class="fw-bold mb-1" style="font-size: 38px; letter-spacing: -1.5px; color: #fff;">SafeOrbit</h2>
            <p class="mb-5" style="color: rgba(255, 255, 255, 0.4); font-weight: 500; font-size: 16px;">Premium CRM Experience</p>
            <form action="/login" method="post" class="text-start">
                <div class="mb-4">
                    <label class="form-label">Телефон</label>
                    <input name="username" type="tel" class="form-control" placeholder="+380..." required>
                </div>
                <div class="mb-5">
                    <label class="form-label">Пароль</label>
                    <input name="password" type="password" class="form-control" placeholder="••••••••" required>
                </div>
                <button class="btn btn-primary text-white">Увійти</button>
                <a href="/login-demo" class="btn-demo"><i class="fas fa-flask text-info"></i>Тестовий акаунт</a>
                <div class="text-center mt-5">
                    <a href="/register" class="text-link">Немає акаунту? <span style="color: #ffffff;">Створити бізнес</span></a>
                </div>
            </form>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <script>
    const urlParams = new URLSearchParams(window.location.search);
    if(urlParams.get('msg') === 'registered') {{
        Swal.fire({{
            title: 'Успішно!',
            text: 'Заявка відправлена. Адміністратор активує ваш акаунт після перевірки.',
            icon: 'success',
            background: 'rgba(20, 20, 20, 0.95)',
            color: '#fff',
            confirmButtonColor: '#af85ff',
            customClass: {{ popup: 'glass-card' }}
        }});
        window.history.replaceState(null, null, window.location.pathname);
    }}
    </script>
    </body></html>"""


@router.get("/login-demo")
async def login_demo(request: Request, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where(User.username == "+380999999999"))
    user = res.scalar_one_or_none()
    if user:
        request.session["user_id"] = user.id
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).options(joinedload(User.business)).where(User.username == username))
    user = res.scalar_one_or_none()
    
    if not user: return RedirectResponse("/", status_code=303)
    if not verify_password(password, user.password): return RedirectResponse("/", status_code=303)
    if user.role == "owner" and user.business and not user.business.is_active:
        return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Блокування</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>body {{ background: #fef2f2; height: 100vh; display: flex; align-items: center; justify-content: center; font-family: 'Plus Jakarta Sans', sans-serif; letter-spacing: -0.02em; }}</style>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap" rel="stylesheet"></head>
        <body><div class="text-center p-5 bg-white shadow rounded-4" style="max-width: 500px;">
            <div class="mb-4"><span class="fa-stack fa-3x"><i class="fas fa-circle fa-stack-2x text-danger opacity-25"></i><i class="fas fa-lock fa-stack-1x text-danger"></i></span></div>
            <h2 class="fw-bold text-dark mb-3">Акаунт Заблоковано</h2>
            <p class="text-muted mb-4">Доступ до вашого акаунту тимчасово призупинено.<br>Зверніться до адміністратора.</p>
            <a href="/" class="btn btn-outline-danger px-4 rounded-pill">Повернутися</a>
        </div></body></html>""", status_code=403)
    
    request.session["user_id"] = user.id
    return RedirectResponse("/superadmin" if user.role == "superadmin" else "/admin", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)