import re
from utils.templates import render_template
import html
from models import User
from config import LABELS
from dependencies import can_access_workspace

def get_layout(content: str, user: User, active: str, scripts: str = ""):
    is_demo = getattr(user, "is_demo_workspace", False)
    is_super = user.role == "superadmin"
    is_master = user.role == "master"
    is_admin = user.role == "admin"
    is_owner = user.role == "owner"
    
    biz_type = user.business.type if user.business else "barbershop"
    is_retail = biz_type == "retail"
    l = LABELS.get(biz_type, LABELS["generic"])
    
    # Sidebar menu items
    menu_items = []
    if is_super:
        menu_items.append(("/superadmin", "super", "fa-user-shield", "Адмінпанель"))
    else:
        menu_items.append(("/admin", "dash", "fa-house", "Огляд"))
        if can_access_workspace(user):
            menu_items.append(("/workspace", "workspace", "fa-table-cells-large", "Робочий простір"))
        menu_items.append(("/admin#day-agenda", "agenda", "fa-calendar-days", "Записи"))
        menu_items.append(("/admin/klienci", "kli", "fa-users", l['clients']))
        if not is_master:
            menu_items.append(("/admin/reports", "reports", "fa-chart-line", "Звіти"))
            menu_items.append(("/admin/generator", "gen", "fa-wand-magic-sparkles", "AI Сервіс"))
            menu_items.append(("/admin/finance", "fin", "fa-boxes-stacked", "Склад"))
            menu_items.append(("/admin/logs", "logs", "fa-clock-rotate-left", "Журнал подій"))
        menu_items.append(("/admin/settings", "set", "fa-gear", "Конфігурація"))
        menu_items.append(("/admin/chats", "chats", "fa-comments", "Комунікації"))
        
        if user.role in ["owner", "admin", "manager"]:
            menu_items.append(("/admin/bot-integration", "bot", "fa-robot", "AI Асистенти"))
        menu_items.append(("/admin/updates", "upd", "fa-bullhorn", "Оновлення"))
        menu_items.append(("/admin/help", "help", "fa-circle-question", "Підтримка"))
    
    if is_demo:
        menu_items = [item for item in menu_items if item[1] in {"dash", "agenda", "kli", "fin", "reports", "logs"}]

    # Generate menu HTML
    menu_html = ""
    for href, key, icon, label in menu_items:
        is_active = 'active' if active == key else ''
        menu_html += f'<a href="{href}" id="menu-{key}" class="nav-link {is_active}"><i class="fas {icon}" aria-hidden="true"></i><span>{label}</span></a>'
    
    # User pill
    user_dropdown = f"""
    <div class="user-pill">
        <div class="user-avatar">{html.escape(user.username[:2].upper())}</div>
        <div class="user-info">
            <span class="user-name">{html.escape(user.username)}</span>
            <span class="user-role">{'Адміністратор' if is_super else ('Експерт' if is_master else 'Власник')}</span>
        </div>
        <a href="/logout" class="logout-icon" title="Завершити сесію"><i class="fas fa-power-off"></i></a>
    </div>"""
    
    if user.role in {"owner", "admin"} and not is_demo:
        menu_html += '<a href="/admin/settings" class="nav-link"><i class="fas fa-code" aria-hidden="true"></i><span>API та інтеграції</span></a>'
    title_map = {
        "dash": "Огляд бізнесу", "reports": "Звіти", "super": "Панель адміністратора", "set": "Налаштування",
        "fin": "Фінанси та склад", "cust": l["clients"], "kli": l["clients"],
        "api": "API та інтеграції", "crm": "Клієнти та CRM", "anal": "Аналітика",
        "masters": l["masters"], "services": l["services"], "users": "Команда",
    }
    title = title_map.get(active, "Робочий простір")
    # Untrusted names are escaped by Jinja; role-aware menu HTML is generated above.
    username = user.username or "Користувач"
    business_name = getattr(user.business, "name", None) or ("SafeOrbit Admin" if is_super else "Мій бізнес")
    menu_html = re.sub(r'<a href="/logout".*?</a>', "", menu_html, flags=re.S)
    menu_html = menu_html.replace('class="nav-link active"', 'class="nav-item active" aria-current="page"')
    menu_html = re.sub(r'class="nav-link\s*"', 'class="nav-item"', menu_html)
    return render_template(
        "app/shell.html", content=content, scripts=scripts, menu_html=menu_html,
        title=title, active=active, is_demo=is_demo, business_name=business_name, username=username,
        username_initial=username[:1].upper(), initials=business_name[:2].upper(),
        role_label={"superadmin": "Адміністратор платформи", "owner": "Власник бізнесу",
                    "admin": "Адміністратор", "manager": "Менеджер", "master": "Спеціаліст"}.get(user.role, "Команда"),
        home="/superadmin" if is_super else "/admin",
        needs_chart="Chart(" in content + scripts or "new Chart" in content + scripts,
        needs_calendar="FullCalendar" in content + scripts,
    )

def get_api_docs_html() -> str:
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SafeOrbit API Reference</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script defer src="/static/locales/catalog.js?v=sale-locales2"></script>
    <script defer src="/static/i18n.js?v=sale-locales2"></script>
    <!-- PrismJS for Syntax Highlighting -->
    <link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" rel="stylesheet" />
    <style>
        :root {
            --bg-base: #0a0a0a;
            --bg-sidebar: #111111;
            --bg-card: #141414;
            --bg-code: #000000;
            --text-main: #ededed;
            --text-muted: #a1a1aa;
            --border-color: #27272a;
            --accent: #BB86FC;
            --accent-glow: rgba(187, 134, 252, 0.2);
            --method-get: #3b82f6;
            --method-post: #10b981;
            --method-put: #f59e0b;
            --method-delete: #ef4444;
            --sidebar-width: 280px;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg-base);
            color: var(--text-main);
            line-height: 1.6;
            display: flex;
            overflow-x: hidden;
        }
        
        /* --- Sidebar --- */
        .sidebar {
            width: var(--sidebar-width);
            height: 100vh;
            position: fixed;
            top: 0;
            left: 0;
            background-color: var(--bg-sidebar);
            border-right: 1px solid var(--border-color);
            padding: 32px 24px;
            overflow-y: auto;
            z-index: 100;
        }
        
        .logo {
            font-size: 20px;
            font-weight: 800;
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 40px;
            color: #fff;
            text-decoration: none;
        }
        .logo i { color: var(--accent); }
        
        .nav-group { margin-bottom: 24px; }
        .nav-group-title {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            font-weight: 700;
            margin-bottom: 12px;
        }
        .nav-link {
            display: block;
            color: var(--text-muted);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            padding: 8px 12px;
            border-radius: 8px;
            margin-bottom: 4px;
            transition: all 0.2s;
        }
        .nav-link:hover { color: var(--text-main); background: rgba(255,255,255,0.05); }
        .nav-link.active { color: var(--accent); background: var(--accent-glow); font-weight: 600; }
        
        /* --- Main Content --- */
        .main-content {
            margin-left: var(--sidebar-width);
            padding: 60px 40px 100px;
            max-width: 860px;
            width: 100%;
        }
        
        h1, h2, h3, h4 { color: #fff; font-weight: 700; margin-bottom: 16px; letter-spacing: -0.02em; }
        h1 { font-size: 36px; margin-bottom: 24px; }
        h2 { font-size: 24px; margin-top: 48px; border-bottom: 1px solid var(--border-color); padding-bottom: 12px; }
        h3 { font-size: 18px; margin-top: 32px; }
        
        p { margin-bottom: 16px; color: var(--text-muted); }
        a { color: var(--accent); text-decoration: none; }
        a:hover { text-decoration: underline; }
        
        ul { margin-bottom: 16px; padding-left: 20px; color: var(--text-muted); }
        li { margin-bottom: 8px; }
        
        .endpoint-block {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 32px;
            margin-top: 24px;
        }
        
        .endpoint-header {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 16px;
            font-family: 'Fira Code', monospace;
            font-size: 14px;
            background: #000;
            padding: 12px 16px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }
        
        .method {
            font-weight: 700;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 12px;
        }
        .method.get { background: rgba(59, 130, 246, 0.1); color: var(--method-get); border: 1px solid rgba(59, 130, 246, 0.2); }
        .method.post { background: rgba(16, 185, 129, 0.1); color: var(--method-post); border: 1px solid rgba(16, 185, 129, 0.2); }
        .method.put { background: rgba(245, 158, 11, 0.1); color: var(--method-put); border: 1px solid rgba(245, 158, 11, 0.2); }
        .method.delete { background: rgba(239, 68, 68, 0.1); color: var(--method-delete); border: 1px solid rgba(239, 68, 68, 0.2); }
        
        .url { color: #fff; }
        
        /* --- Code Blocks --- */
        .code-container {
            position: relative;
            margin: 24px 0;
            border-radius: 12px;
            overflow: hidden;
            background: var(--bg-code);
            border: 1px solid var(--border-color);
        }
        
        .code-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255,255,255,0.05);
            padding: 8px 16px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .mac-dots { display: flex; gap: 6px; }
        .dot { width: 10px; height: 10px; border-radius: 50%; }
        .dot.red { background: #ff5f56; }
        .dot.yellow { background: #ffbd2e; }
        .dot.green { background: #27c93f; }
        
        .copy-btn {
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Inter', sans-serif;
        }
        .copy-btn:hover { background: rgba(255,255,255,0.1); color: #fff; }
        .copy-btn.copied { color: #10b981; border-color: #10b981; }
        
        pre[class*="language-"] {
            margin: 0 !important;
            padding: 16px !important;
            background: transparent !important;
            font-size: 13px !important;
            border-radius: 0 0 12px 12px !important;
        }
        
        /* --- Tabs --- */
        .tabs {
            display: flex;
            border-bottom: 1px solid var(--border-color);
            background: rgba(255,255,255,0.02);
        }
        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 10px 16px;
            font-size: 13px;
            font-family: 'Fira Code', monospace;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: 0.2s;
        }
        .tab-btn:hover { color: #fff; }
        .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
        .tab-pane { display: none; }
        .tab-pane.active { display: block; }
        
        /* --- Auth Block --- */
        .auth-block {
            background: rgba(187, 134, 252, 0.05);
            border: 1px solid var(--accent-glow);
            border-left: 4px solid var(--accent);
            padding: 20px;
            border-radius: 8px;
            margin: 24px 0;
        }
        .auth-block code {
            background: #000;
            padding: 6px 12px;
            border-radius: 6px;
            font-family: 'Fira Code', monospace;
            color: var(--accent);
            font-size: 14px;
        }
        
        /* Mobile Responsive */
        @media (max-width: 768px) {
            .sidebar { transform: translateX(-100%); transition: 0.3s; }
            .main-content { margin-left: 0; padding: 40px 20px; }
        }
    </style>
</head>
<body>

    <nav class="sidebar">
        <a href="#" class="logo"><i class="fas fa-bolt"></i> SafeOrbit</a>
        
        <div class="nav-group">
            <div class="nav-group-title">Introduction</div>
            <a href="#getting-started" class="nav-link active">Getting Started</a>
            <a href="#authentication" class="nav-link">Authentication</a>
            <a href="#quick-start" class="nav-link">Quick Start</a>
        </div>
        
        <div class="nav-group">
            <div class="nav-group-title">API Reference</div>
            <a href="#endpoints-customers" class="nav-link">Customers</a>
            <a href="#endpoints-appointments" class="nav-link">Appointments</a>
            <a href="#endpoints-api-keys" class="nav-link">API Keys</a>
            <a href="#endpoints-webhooks" class="nav-link">Webhooks</a>
            <a href="#endpoints-chat" class="nav-link">Chat API</a>
        </div>
        
        <div class="nav-group">
            <div class="nav-group-title">Guides</div>
            <a href="#errors" class="nav-link">Errors</a>
            <a href="#best-practices" class="nav-link">Best Practices</a>
        </div>
    </nav>

    <main class="main-content">
        <h1 id="getting-started">SafeOrbit API Reference</h1>
        <p>Ласкаво просимо до документації SafeOrbit API. Наш REST API створений для розробників і дозволяє легко інтегрувати можливості нашої CRM-системи у ваші власні продукти, веб-сайти або мобільні додатки.</p>
        <p>Завдяки API ви можете керувати клієнтами, автоматизувати створення записів (бронювань), керувати API-ключами та отримувати події в реальному часі через Webhooks.</p>
        <p>API побудовано за принципами REST. Ми використовуємо стандартні HTTP-методи, повертаємо відповіді у форматі JSON та використовуємо стандартні HTTP-коди для індикації помилок.</p>

        <h2 id="authentication">🔐 Authentication</h2>
        <p>SafeOrbit API використовує API-ключі для автентифікації запитів. Ви можете керувати своїми ключами у панелі керування або через сам API.</p>
        <p>Ваш API-ключ має передаватися у кожному запиті через HTTP-заголовок <code>X-API-Key</code>.</p>

        <div class="auth-block d-flex justify-content-between align-items-center">
            <div>
                <span style="color: var(--text-muted); font-size: 12px; display: block; margin-bottom: 4px;">Приклад заголовка:</span>
                <code>X-API-Key: sk_live_a8ba0cf96d1f43adac2b3632aaa7f2426</code>
            </div>
            <button class="copy-btn" onclick="copyText('X-API-Key: sk_live_a8ba0cf96d1f43adac2b3632aaa7f2426', this)">Copy</button>
        </div>

        <p><strong>Увага:</strong> Ваші API-ключі мають повні привілеї для доступу до даних вашого бізнесу. Зберігайте їх у безпеці! Ніколи не передавайте ключі в публічних репозиторіях (наприклад, GitHub) або у клієнтському коді (браузерний JavaScript, мобільні додатки).</p>

        <h2 id="quick-start">⚡ Quick Start</h2>
        <p>Ось як виглядає базовий запит до нашого API для отримання списку всіх активних записів (appointments).</p>

        <div class="code-container">
            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab('quick-start', 'curl')">cURL</button>
                <button class="tab-btn" onclick="switchTab('quick-start', 'python')">Python</button>
                <button class="tab-btn" onclick="switchTab('quick-start', 'js')">JavaScript</button>
            </div>
            <div id="quick-start-curl" class="tab-pane active">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-bash">curl -X GET "https://api.safeorbit.com/api/v1/appointments" \\
  -H "X-API-Key: sk_live_your_secret_api_key_here" \\
  -H "Content-Type: application/json"</code></pre>
            </div>
            <div id="quick-start-python" class="tab-pane">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-python">import requests

API_KEY = "sk_live_your_secret_api_key_here"
BASE_URL = "https://api.safeorbit.com/api/v1"

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

response = requests.get(f"{BASE_URL}/appointments", headers=headers)
print(response.json())</code></pre>
            </div>
            <div id="quick-start-js" class="tab-pane">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-javascript">const API_KEY = "sk_live_your_secret_api_key_here";
const BASE_URL = "https://api.safeorbit.com/api/v1";

fetch(`${BASE_URL}/appointments`, {
  method: "GET",
  headers: {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
  }
})
  .then(res => res.json())
  .then(data => console.log(data));</code></pre>
            </div>
        </div>

        <!-- CUSTOMERS ENDPOINTS -->
        <h2 id="endpoints-customers">👥 Клієнти (Customers)</h2>
        <p>Перед створенням запису вам необхідно створити клієнта, щоб отримати його <code>id</code>.</p>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method post">POST</span>
                <span class="url">/api/v1/customers</span>
            </div>
            <p>Створює нового клієнта у вашій базі.</p>
            
            <h4>Request Body (JSON)</h4>
            <div class="code-container">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-json">{
  "name": "Олена Коваленко",
  "phone_number": "+380501234567",
  "notes": "VIP клієнт",
  "discount_percent": 10.0
}</code></pre>
            </div>

            <h4>Response <span style="color: #10b981; font-size: 14px; font-weight: 500;">201 Created</span></h4>
            <div class="code-container">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-json">{
  "id": 42,
  "business_id": 11,
  "name": "Олена Коваленко",
  "phone_number": "+380501234567",
  "notes": "VIP клієнт",
  "discount_percent": 10.0,
  "is_blocked": false
}</code></pre>
            </div>
        </div>

        <!-- APPOINTMENTS ENDPOINTS -->
        <h2 id="endpoints-appointments">📅 Записи (Appointments)</h2>
        <p>Управління бронюваннями та записами клієнтів.</p>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method post">POST</span>
                <span class="url">/api/v1/appointments</span>
            </div>
            <p>Створює новий запис. <em>Ми наполегливо рекомендуємо використовувати заголовок <code>Idempotency-Key</code> для цього запиту.</em></p>
            
            <h4>Headers</h4>
            <ul>
                <li><code>Idempotency-Key</code>: унікальний-рядок-запиту (наприклад, UUID).</li>
            </ul>

            <h4>Request Body</h4>
            <div class="code-container">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-json">{
  "customer_id": 42,
  "master_id": 5,
  "appointment_time": "2026-04-20T14:30:00",
  "service_type": "Манікюр",
  "cost": 550.0
}</code></pre>
            </div>
        </div>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method get">GET</span>
                <span class="url">/api/v1/appointments</span>
            </div>
            <p>Отримує список записів. Можна фільтрувати за статусом: <code>?status=confirmed</code>.</p>
        </div>

        <!-- API KEYS ENDPOINTS -->
        <h2 id="endpoints-api-keys">🔑 API Ключі (API Keys)</h2>
        
        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method post">POST</span>
                <span class="url">/api/v1/api-keys</span>
            </div>
            <p>Створює новий API-ключ.</p>
            <div class="code-container"><pre><code class="language-json">{
  "name": "Integration Key - Website"
}</code></pre></div>
        </div>

        <!-- WEBHOOKS ENDPOINTS -->
        <h2 id="endpoints-webhooks">🔗 Вебхуки (Webhooks)</h2>
        <p>Webhooks дозволяють вашому серверу миттєво реагувати на події в CRM (наприклад, <code>appointment.created</code>). Наша система забезпечує надійну доставку з 3 спробами (Retry: 1s, 5s, 15s).</p>
        
        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method post">POST</span>
                <span class="url">/api/v1/webhooks</span>
            </div>
            <p>Реєстрація вашого Webhook URL. У відповідь ви отримаєте унікальний <code>secret</code>, який необхідний для перевірки цифрового підпису подій.</p>
            <div class="code-container">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-json">{
  "url": "https://your-server.com/api/webhooks"
}</code></pre>
            </div>
        </div>

        <h3>Структура події (Payload)</h3>
        <p>Ми будемо відправляти <code>POST</code> запит на ваш URL з наступною структурою:</p>
        <div class="code-container">
            <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
            <pre><code class="language-json">{
  "event_type": "appointment.created",
  "timestamp": "2026-04-21T10:00:00",
  "data": {
    "id": 123,
    "customer_id": 42,
    "service": "Манікюр",
    "time": "2026-04-22T14:00:00"
  },
}</code></pre>
        </div>
        
        <h3>Доступні події</h3>
        <ul>
            <li><code>appointment.created</code> — створено новий запис</li>
            <li><code>appointment.updated</code> — оновлено статус або час запису</li>
            <li><code>customer.created</code> — створено нового клієнта</li>
            <li><code>customer.updated</code> — оновлено дані клієнта</li>
        </ul>

        <h3>🔒 Валідація цифрового підпису (Python Example)</h3>
        <p>Для захисту від підробки запитів, кожна подія містить HTTP заголовок <code>X-Webhook-Signature</code> (HMAC SHA256). Ви <strong>зобов'язані</strong> перевіряти його на своєму сервері.</p>
        <div class="code-container">
            <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
            <pre><code class="language-python">import hmac
import hashlib
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()
WEBHOOK_SECRET = "whsec_ваший_отриманий_секрет"

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

@app.post("/api/webhooks")
async def handle_webhook(request: Request):
    signature = request.headers.get("X-Webhook-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")
        
    raw_body = await request.body()
    
    if not verify_signature(raw_body, signature, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Invalid signature")
        
    event = await request.json()
    print(f"Отримано безпечну подію: {event['event_type']}")
    
    return {"status": "success"}</code></pre>
            </div>
        </div>
        
        <!-- CHAT API ENDPOINTS -->
        <h2 id="endpoints-chat">💬 Chat / Messaging API</h2>
        <p>Этот API позволяет внешним CRM отображать список диалогов (как чат), получать сообщения и отвечать клиентам через SafeOrbit.</p>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method get">GET</span>
                <span class="url">/api/v1/chat/conversations</span>
            </div>
            <p>Отримати список всіх діалогів (Діалоги). Сортування за <code>updated_at DESC</code>. Повертаються останні повідомлення, кількість непрочитаних та дані клієнта.</p>
        </div>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method get">GET</span>
                <span class="url">/api/v1/chat/conversations/{id}</span>
            </div>
            <p>Відкрити конкретний діалог (отримати деталі діалогу та історію повідомлень).</p>
        </div>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method get">GET</span>
                <span class="url">/api/v1/chat/conversations/{id}/messages</span>
            </div>
            <p>Підвантажити історію повідомлень. Підтримує параметри <code>limit</code> та <code>before</code> для пагінації.</p>
        </div>

        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method post">POST</span>
                <span class="url">/api/v1/chat/send</span>
            </div>
            <p>Відправити повідомлення клієнту безпосередньо в канал комунікації (Telegram, Viber або Web Віджет).</p>
            <h4>Request Body</h4>
            <div class="code-container">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-json">{
  "conversation_id": "tg_123456",
  "text": "Привіт! Ваш запис підтверджено."
}</code></pre>
            </div>
        </div>
        
        <div class="endpoint-block">
            <div class="endpoint-header">
                <span class="method get">GET</span>
                <span class="url">/api/v1/chat/widget</span>
            </div>
            <p><strong>Готовий Iframe Віджет:</strong> Повноцінний візуальний інтерфейс чату (UI) для вбудовування в інші платформи. Не потребує написання фронтенд-коду. Ключ доступу передається через URL.</p>
            <div class="code-container">
                <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
                <pre><code class="language-html">&lt;iframe 
  src="https://api.safeorbit.com/api/v1/chat/widget?api_key=sk_live_ваший_ключ" 
  width="100%" 
  height="600px" 
  frameborder="0"
&gt;&lt;/iframe&gt;</code></pre>
            </div>
        </div>

        <h3>Приклад інтеграції (Python)</h3>
        <div class="code-container">
            <div class="code-header"><div class="mac-dots"><div class="dot red"></div><div class="dot yellow"></div><div class="dot green"></div></div><button class="copy-btn" onclick="copyCode(this)">Copy</button></div>
            <pre><code class="language-python">import requests

headers = {"X-API-Key": "sk_live_your_key"}

# список диалогов
requests.get("https://api.safeorbit.com/api/v1/chat/conversations", headers=headers)

# открыть диалог
requests.get("https://api.safeorbit.com/api/v1/chat/conversations/tg_123456", headers=headers)

# отправить сообщение
requests.post("https://api.safeorbit.com/api/v1/chat/send", json={
    "conversation_id": "tg_123456",
    "text": "Привіт!"
}, headers=headers)</code></pre>
        </div>

        <h2 id="errors">⚠️ Errors</h2>
        <p>Ми використовуємо стандартні HTTP коди статусів. Кожна помилка повертається у єдиному структурованому форматі JSON.</p>
        
        <div class="code-container">
            <pre><code class="language-json">{
  "error": {
    "code": "invalid_api_key",
    "message": "Invalid or inactive API key"
  }
}</code></pre>
        </div>

        <ul>
            <li><strong><code>400 Bad Request</code></strong> — Запит недійсний (наприклад, пропущено обов'язкове поле у JSON або формат невірний).</li>
            <li><strong><code>401 Unauthorized</code></strong> — Відсутній або недійсний заголовок `X-API-Key`.</li>
            <li><strong><code>403 Forbidden</code></strong> — Ключ дійсний, але не має прав для виконання цієї дії.</li>
            <li><strong><code>404 Not Found</code></strong> — Запитуваний ресурс не знайдено, або він вам не належить.</li>
            <li><strong><code>409 Conflict</code></strong> — Конфлікт станів (наприклад, помилка `Idempotency-Key`).</li>
            <li><strong><code>429 Too Many Requests</code></strong> — Ви перевищили ліміт запитів (Rate Limit). Зачекайте хвилину.</li>
            <li><strong><code>500 Internal Server Error</code></strong> — Проблема на нашому боці. Ми вже працюємо над її вирішенням.</li>
        </ul>

        <h2 id="best-practices">🧠 Best Practices</h2>
        <ul>
            <li><strong>Бережіть ключі:</strong> Ніколи не вставляйте `sk_live_...` ключі безпосередньо у фронтенд-код (React/Vue) або мобільні додатки. Всі запити до SafeOrbit мають йти через ваш власний бекенд-сервер.</li>
            <li><strong>Використовуйте Idempotency-Key:</strong> Мережа не ідеальна. Якщо запит `POST /appointments` обірвався через таймаут, передавайте унікальний заголовок `Idempotency-Key` (наприклад, згенерований UUID). Якщо ви повторите запит з тим самим ключем, ми не створимо дублікат.</li>
            <li><strong>Обробляйте Rate Limits (429):</strong> API дозволяє до 100 запитів на хвилину. Реалізуйте логіку `Exponential Backoff` у вашому коді.</li>
            <li><strong>Валідуйте Webhooks:</strong> Завжди перевіряйте заголовок `X-Webhook-Signature` у ваших ендпоінтах. Це єдина гарантія того, що запит надійшов саме від наших серверів.</li>
        </ul>

    </main>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js"></script>
    <script>
        // Tab Switching
        function switchTab(group, tab) {
            const container = document.getElementById(`${group}-${tab}`).parentElement.parentElement;
            container.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            container.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById(`${group}-${tab}`).classList.add('active');
        }

        // Copy to clipboard
        function copyCode(btn) {
            const codeBlock = btn.parentElement.nextElementSibling.innerText;
            copyText(codeBlock, btn);
        }

        function copyText(text, btn) {
            navigator.clipboard.writeText(text).then(() => {
                const originalText = btn.innerText;
                btn.innerText = 'Copied!';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.innerText = originalText;
                    btn.classList.remove('copied');
                }, 2000);
            });
        }

        // Scroll Spy for Sidebar
        const sections = document.querySelectorAll("h1, h2");
        const navLinks = document.querySelectorAll(".nav-link");

        window.addEventListener("scroll", () => {
            let current = "";
            sections.forEach((section) => {
                const sectionTop = section.offsetTop;
                if (scrollY >= sectionTop - 100) {
                    current = section.getAttribute("id");
                }
            });

            navLinks.forEach((link) => {
                link.classList.remove("active");
                if (link.getAttribute("href") === `#${current}`) {
                    link.classList.add("active");
                }
            });
        });
    </script>
</body>
</html>"""

def get_chat_widget_html() -> str:
    """
    Повертає готову HTML-сторінку віджета чату.
    Використовується для вбудовування через Iframe у зовнішні CRM.
    """
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SafeOrbit Chat Widget</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script defer src="/static/locales/catalog.js?v=sale-locales2"></script>
    <script defer src="/static/i18n.js?v=sale-locales2"></script>
    <style>
        :root {
            --primary: #9D4EDD;
            --primary-hover: #7b2cbf;
            --bg: #f8fafc;
            --surface: #ffffff;
            --border: #e2e8f0;
            --text-main: #0f172a;
            --text-muted: #64748b;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', sans-serif; }
        body { display: flex; height: 100vh; overflow: hidden; background: var(--bg); color: var(--text-main); }
        
        /* Sidebar */
        .sidebar { width: 320px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; }
        .sidebar-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
        .sidebar-title { font-weight: 700; font-size: 16px; }
        .conv-list { flex: 1; overflow-y: auto; }
        .conv-item { padding: 16px 20px; border-bottom: 1px solid var(--border); cursor: pointer; transition: 0.2s; display: flex; gap: 12px; }
        .conv-item:hover { background: #f1f5f9; }
        .conv-item.active { background: #f3e8ff; border-left: 4px solid var(--primary); }
        .avatar { width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg, var(--primary), #e0aaff); color: white; display: flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0; }
        .conv-content { flex: 1; min-width: 0; }
        .conv-top { display: flex; justify-content: space-between; margin-bottom: 4px; }
        .conv-name { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .conv-time { font-size: 11px; color: var(--text-muted); }
        .conv-msg { font-size: 13px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        /* Chat Area */
        .chat-area { flex: 1; display: flex; flex-direction: column; background: var(--bg); }
        .chat-header { padding: 16px 24px; background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; height: 73px; }
        .chat-header .avatar { width: 36px; height: 36px; font-size: 14px; }
        .messages { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; scroll-behavior: smooth; }
        
        .msg-wrapper { display: flex; flex-direction: column; max-width: 70%; }
        .msg-wrapper.client { align-self: flex-start; }
        .msg-wrapper.business { align-self: flex-end; }
        
        .msg-bubble { padding: 12px 16px; border-radius: 16px; font-size: 14px; line-height: 1.5; position: relative; }
        .msg-wrapper.client .msg-bubble { background: var(--surface); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
        .msg-wrapper.business .msg-bubble { background: var(--primary); color: white; border-bottom-right-radius: 4px; }
        
        .msg-time { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
        .msg-wrapper.business .msg-time { text-align: right; }
        
        /* Input Area */
        .input-area { padding: 16px 24px; background: var(--surface); border-top: 1px solid var(--border); display: flex; gap: 12px; align-items: center; }
        .input-area input { flex: 1; padding: 14px 20px; border: 1px solid var(--border); border-radius: 24px; outline: none; font-size: 14px; background: #f8fafc; transition: 0.2s; }
        .input-area input:focus { border-color: var(--primary); background: #fff; box-shadow: 0 0 0 3px rgba(157, 78, 221, 0.1); }
        .send-btn { width: 44px; height: 44px; border-radius: 50%; background: var(--primary); color: white; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: 0.2s; flex-shrink: 0; }
        .send-btn:hover:not(:disabled) { background: var(--primary-hover); transform: scale(1.05); }
        .send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); gap: 16px; }
        .empty-state i { font-size: 48px; opacity: 0.2; }
        
        .channel-icon { font-size: 12px; margin-right: 4px; }
        .telegram { color: #0088cc; }
        .viber { color: #7360f2; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <span class="sidebar-title">Діалоги</span>
        </div>
        <div class="conv-list" id="convList">
            <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 14px;">Завантаження...</div>
        </div>
    </div>
    
    <div class="chat-area">
        <div class="chat-header" id="chatHeader" style="display: none;">
            <div class="avatar" id="headerAvatar"></div>
            <div>
                <div style="font-weight: 600; font-size: 15px;" id="headerName"></div>
                <div style="font-size: 12px; color: var(--text-muted);" id="headerChannel"></div>
            </div>
        </div>
        
        <div class="messages" id="messagesArea">
            <div class="empty-state">
                <i class="far fa-comments"></i>
                <p>Оберіть діалог для початку спілкування</p>
            </div>
        </div>
        
        <div class="input-area" id="inputArea" style="opacity: 0.5; pointer-events: none;">
            <input type="text" id="msgInput" placeholder="Написати повідомлення..." onkeypress="if(event.key === 'Enter') sendMsg()">
            <button class="send-btn" id="sendBtn" onclick="sendMsg()"><i class="fas fa-paper-plane"></i></button>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const API_KEY = urlParams.get('api_key');
        const BASE_URL = "/api/v1"; // Запити йтимуть на поточний домен

        let currentConvId = null;
        let pollingInterval = null;

        const headers = {
            "Content-Type": "application/json",
            "X-API-Key": API_KEY
        };

        function formatTime(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            return d.toLocaleTimeString('uk-UA', {hour: '2-digit', minute:'2-digit'});
        }

        function getChannelIcon(channel) {
            if(channel === 'telegram') return '<i class="fab fa-telegram telegram channel-icon"></i>';
            if(channel === 'viber') return '<i class="fab fa-viber viber channel-icon"></i>';
            return '<i class="fas fa-globe channel-icon"></i>';
        }

        async function loadConversations() {
            if (!API_KEY) {
                document.getElementById('convList').innerHTML = '<div style="padding: 24px; color: #ef4444; font-size: 14px; text-align: center;">Помилка: Відсутній параметр ?api_key у URL</div>';
                return;
            }
            try {
                const res = await fetch(`${BASE_URL}/chat/conversations`, { headers });
                if (!res.ok) throw new Error('API Error');
                const data = await res.json();
                
                const list = document.getElementById('convList');
                if (data.length === 0) {
                    list.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 14px;">Немає діалогів</div>';
                    return;
                }

                list.innerHTML = data.map(conv => {
                    const name = conv.customer?.name || 'Клієнт';
                    const initial = name.charAt(0).toUpperCase();
                    const isActive = conv.id === currentConvId ? 'active' : '';
                    const time = formatTime(conv.updated_at);
                    
                    return `
                        <div class="conv-item ${isActive}" onclick="openConversation('${conv.id}', '${name.replace(/'/g, "\\'")}', '${conv.channel}')">
                            <div class="avatar">${initial}</div>
                            <div class="conv-content">
                                <div class="conv-top">
                                    <span class="conv-name">${name}</span>
                                    <span class="conv-time">${time}</span>
                                </div>
                                <div class="conv-msg">
                                    ${getChannelIcon(conv.channel)} 
                                    ${conv.last_message?.text || '...'}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (e) {
                console.error('Failed to load conversations', e);
            }
        }

        async function openConversation(id, name, channel) {
            currentConvId = id;
            
            // Оновити шапку
            document.getElementById('chatHeader').style.display = 'flex';
            document.getElementById('headerAvatar').innerText = name.charAt(0).toUpperCase();
            document.getElementById('headerName').innerText = name;
            document.getElementById('headerChannel').innerHTML = `${getChannelIcon(channel)} ${channel === 'telegram' ? 'Telegram' : channel}`;
            
            // Розблокувати введення
            const inputArea = document.getElementById('inputArea');
            inputArea.style.opacity = '1';
            inputArea.style.pointerEvents = 'auto';
            document.getElementById('msgInput').focus();
            
            await loadMessages(true);
            
            // Почати авто-оновлення (Polling 3 секунди)
            if (pollingInterval) clearInterval(pollingInterval);
            pollingInterval = setInterval(() => {
                loadConversations();
                if(currentConvId) loadMessages(false);
            }, 3000);
            
            loadConversations();
        }

        async function loadMessages(forceScroll = false) {
            if (!currentConvId) return;
            try {
                const res = await fetch(`${BASE_URL}/chat/conversations/${currentConvId}`, { headers });
                const data = await res.json();
                const msgs = data.messages || [];
                const area = document.getElementById('messagesArea');
                
                if (msgs.length === 0) {
                    area.innerHTML = '<div class="empty-state"><p>Немає повідомлень</p></div>';
                    return;
                }

                // Перевірка чи скрол знаходиться внизу перед оновленням
                const isAtBottom = area.scrollHeight - area.scrollTop <= area.clientHeight + 100;

                area.innerHTML = msgs.map(m => `
                    <div class="msg-wrapper ${m.sender_type}">
                        <div class="msg-bubble">${m.text}</div>
                        <div class="msg-time">${formatTime(m.created_at)}</div>
                    </div>
                `).join('');

                if (forceScroll || isAtBottom) {
                    area.scrollTop = area.scrollHeight;
                }
            } catch (e) {
                console.error('Failed to load messages', e);
            }
        }

        async function sendMsg() {
            const input = document.getElementById('msgInput');
            const btn = document.getElementById('sendBtn');
            const text = input.value.trim();
            if (!text || !currentConvId) return;

            input.value = '';
            input.disabled = true;
            btn.disabled = true;
            
            // Моментально показати повідомлення в UI (Оптимістичний підхід)
            const area = document.getElementById('messagesArea');
            area.innerHTML += `
                <div class="msg-wrapper business" style="opacity:0.6;">
                    <div class="msg-bubble">${text}</div>
                    <div class="msg-time">Відправка...</div>
                </div>
            `;
            area.scrollTop = area.scrollHeight;

            try {
                await fetch(`${BASE_URL}/chat/send`, {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({
                        conversation_id: currentConvId,
                        text: text
                    })
                });
                await loadMessages(true);
                await loadConversations();
            } catch (e) {
                alert("Помилка відправки повідомлення");
            } finally {
                input.disabled = false;
                btn.disabled = false;
                input.focus();
            }
        }

        // Запуск
        loadConversations();
    </script>
</body>
</html>"""
