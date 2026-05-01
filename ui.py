import html
from models import User
from config import LABELS

def get_layout(content: str, user: User, active: str, scripts: str = ""):
    is_super = user.role == "superadmin"
    is_master = user.role == "master"
    is_admin = user.role == "admin"
    is_owner = user.role == "owner"
    
    biz_type = user.business.type if user.business else "barbershop"
    l = LABELS.get(biz_type, LABELS["generic"])
    
    # Sidebar menu items
    menu_items = []
    if is_super:
        menu_items.append(("/superadmin", "super", "fa-user-shield", "Адмінпанель"))
    else:
        menu_items.append(("/admin", "dash", "fa-chart-pie", "Аналітика"))
        menu_items.append(("/admin/klienci", "kli", "fa-users", l['clients']))
        if not is_master:
            menu_items.append(("/admin/generator", "gen", "fa-wand-magic-sparkles", "AI Сервіс"))
            menu_items.append(("/admin/finance", "fin", "fa-boxes-stacked", "Склад"))
            menu_items.append(("/admin/logs", "logs", "fa-clock-rotate-left", "Журнал подій"))
        menu_items.append(("/admin/settings", "set", "fa-gear", "Конфігурація"))
        menu_items.append(("/admin/chats", "chats", "fa-comments", "Комунікації"))
        
        if user.role in ["owner", "admin", "manager"]:
            menu_items.append(("/admin/bot-integration", "bot", "fa-robot", "AI Асистенти"))
        menu_items.append(("/admin/updates", "upd", "fa-bullhorn", "Оновлення"))
        menu_items.append(("/admin/help", "help", "fa-circle-question", "Підтримка"))
    
    # Generate menu HTML
    menu_html = ""
    for href, key, icon, label in menu_items:
        is_active = 'active' if active == key else ''
        menu_html += f'<a href="{href}" id="menu-{key}" class="nav-link {is_active}"><i class="fas {icon}"></i><span>{label}</span></a>'
    
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
    
    return f"""
    <!DOCTYPE html><html lang="uk"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SafeOrbit CRM | Premium B2B</title>
    <link rel="icon" href="/static/favicon.png" type="image/png">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <style>
        *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ overflow-x: hidden; width: 100%; max-width: 100vw; margin: 0; padding: 0; }}
        
        :root {{
            --bg-primary: #0C051A;
            --bg-secondary: #180C33;
            --accent-primary: #BB86FC; /* Softer, slightly brighter purple */
            --accent-secondary: #D0BBFF; /* Lighter shade for highlights */
            --accent-pink: #FFC0CB; /* Soft pink for gradients */
            --glass-bg: rgba(25, 12, 45, 0.3); /* Lighter, more transparent */
            --glass-border: rgba(187, 134, 252, 0.3); /* Matches accent-primary */
            --glass-highlight: rgba(255, 255, 255, 0.1); /* Brighter highlight */
            --text-primary: #F8FAFC;
            --text-secondary: #CBD5E1;
            --text-muted: #94A3B8;
            --success: #10B981;
            --warning: #FFB300; /* More vibrant yellow */
            --danger: #EF4444;
            --info: #3B82F6;
        --blur: 4px; /* Значно зменшуємо розмиття для високої швидкості рендеру */
        }}
        
        /* Tailwind-like Utility Classes */
        .w-full {{ width: 100% !important; max-width: 100% !important; }}
        .max-w-md {{ max-width: 28rem !important; }} /* 448px */
        .mx-auto {{ margin-left: auto !important; margin-right: auto !important; }}
        .overflow-hidden {{ overflow: hidden !important; }}
        .overflow-y-auto {{ overflow-y: auto !important; }}
        .max-h-85vh {{ max-height: 85vh !important; }}
        .whitespace-nowrap {{ white-space: nowrap !important; }}
        .block {{ display: block !important; }}
        .overflow-x-auto {{ overflow-x: auto !important; }}
        .flex-col {{ flex-direction: column !important; }}

        body.sidebar-hidden {{ padding-bottom: 0 !important; }}

        body {{
            font-family: 'Manrope', system-ui, -apple-system, sans-serif;
            background: var(--bg-primary);
            background-attachment: fixed;
            min-height: 100vh;
            width: 100%;
            max-width: 100vw;
            margin: 0;
            padding: 0;
            color: var(--text-primary);
            overflow-x: hidden;
            letter-spacing: -0.01em;
            position: relative;
        }}

        /* Premium Mesh Background */
        body::before {{
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
            z-index: -1;
        }}

        .sidebar {{
            width: 280px;
            background: linear-gradient(180deg, rgba(12, 5, 26, 0.75), rgba(24, 12, 51, 0.75)); /* Gradient for depth */
            border-right: 1px solid var(--glass-border);
            padding: 40px 20px;
            position: fixed;
            height: 100vh;
            display: flex;
            flex-direction: column;
            z-index: 1000;
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        
        .sidebar.hidden {{
            transform: translateX(-100%);
        }}
        
        .sidebar-logo {{
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 48px;
            padding: 0 12px;
        }}
        
        .logo-icon {{
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink));
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            color: white;
            box-shadow: 0 8px 25px rgba(187, 134, 252, 0.4);
        }}
        
        .logo-text {{
            font-size: 24px;
            font-weight: 800;
            color: #FFFFFF;
            letter-spacing: -1px;
        }}
        
        .sidebar-toggle-btn {{
            width: 44px;
            height: 44px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--glass-border);
            color: rgba(255, 255, 255, 0.7);
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            margin-left: auto;
        }}
        
        .sidebar-toggle-btn:hover {{
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
            transform: scale(1.05);
        }}

        .sidebar .nav-link {{
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 14px 18px;
            color: rgba(255, 255, 255, 0.5);
            text-decoration: none !important;
            border-radius: 16px;
            margin-bottom: 8px;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            font-weight: 600;
            font-size: 15px;
            position: relative;
        }}

        .sidebar .nav-link i {{
            font-size: 18px;
            width: 24px;
            text-align: center;
        }}
        
        .sidebar .nav-link:hover {{
            background: rgba(255, 255, 255, 0.05);
            color: #FFFFFF;
            transform: translateX(4px);
        }}
        
        .sidebar .nav-link.active {{
            background: rgba(187, 134, 252, 0.18);
            color: var(--accent-secondary);
            border: 1px solid var(--accent-secondary);
        }}

        .sidebar .nav-link.active::before {{
            content: '';
            position: absolute;
            left: -20px;
            top: 20%;
            height: 60%;
            width: 4px;
            background: var(--accent-secondary);
            border-radius: 0 4px 4px 0;
            box-shadow: 0 0 25px var(--accent-secondary);
        }}

        .main-content {{
            margin-left: 280px;
            padding: 40px;
            min-width: 0;
            flex: 1;
            position: relative;
            transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        
        .main-content.expanded {{
            margin-left: 0 !important;
        }}
        
        .top-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 48px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--glass-border);
        }}

        .header-title-row {{
            display: flex;
            align-items: center;
            gap: 16px;
            flex-direction: row !important;
            min-width: 0;
        }}
        
        .page-title {{
            font-size: 28px;
            font-weight: 800;
            color: #FFFFFF;
            letter-spacing: -1px;
            margin: 0;
            background: linear-gradient(to bottom, #FFFFFF, rgba(255,255,255,0.7));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        /* Search Box Premium */
        .search-box {{
            position: relative;
            width: 340px;
        }}

        .search-box i {{
            position: absolute;
            left: 18px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 14px;
            pointer-events: none;
            transition: color 0.3s;
        }}

        .search-box input {{
            width: 100%;
            padding: 14px 20px 14px 48px !important;
            background: rgba(255, 255, 255, 0.03) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            color: #FFFFFF !important;
            font-size: 14px !important;
            font-weight: 600 !important;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
            backdrop-filter: blur(10px);
        }}

        .search-box input:focus {{
            background: rgba(255, 255, 255, 0.06) !important;
            border-color: var(--accent-primary) !important;
            box-shadow: 0 0 40px rgba(187, 134, 252, 0.25) !important;
            transform: translateY(-1px);
        }}

        .search-box input:focus + i {{
            color: var(--accent-primary);
        }}

        .search-results {{
            position: absolute;
            top: calc(100% + 12px);
            left: 0;
            width: 100%;
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(30px);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.5);
            z-index: 1100;
            display: none;
            overflow: hidden;
            padding: 8px;
        }}

        .search-results.active {{
            display: block;
            animation: slideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .search-result-item {{
            padding: 12px 16px;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .search-result-item:hover {{
            background: rgba(255, 255, 255, 0.05);
        }}

        .search-result-title {{
            font-size: 14px;
            font-weight: 700;
            color: #FFFFFF;
        }}

        .search-result-type {{
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 4px 8px;
            background: rgba(79, 70, 229, 0.1);
            color: var(--accent-secondary);
            border-radius: 6px;
        }}

        .glass-card {{
            background: var(--glass-bg); /* Use rgba with transparency */
            backdrop-filter: blur(var(--blur));
            border: 1px solid var(--glass-border);
            border-radius: 28px;
            padding: 32px;
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
        }}
        
        .glass-card:hover {{
            transform: translateY(-6px);
            border-color: rgba(255, 255, 255, 0.12);
        }}

        /* Tabs & Nav Pills Premium */
        .nav-pills {{
            background: rgba(255, 255, 255, 0.03);
            padding: 8px; /* Slightly larger padding */
            border-radius: 24px; /* More rounded */
            border: 1px solid var(--glass-border);
            display: inline-flex;
            gap: 4px;
        }}

        .nav-pills .nav-link {{
            color: rgba(255, 255, 255, 0.5) !important;
            font-weight: 700;
            font-size: 14px; /* Slightly larger font */
            padding: 10px 20px;
            border-radius: 16px !important; /* More rounded */
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            border: none !important;
            background: transparent !important;
        }}

        .nav-pills .nav-link.active {{
            background: #FFFFFF !important;
            color: #000000 !important;
            box-shadow: 0 4px 15px rgba(255, 255, 255, 0.1);
        }}

        .nav-pills .nav-link:hover:not(.active) {{
            background: rgba(255, 255, 255, 0.05) !important;
            color: #FFFFFF !important;
        }}

        /* Dashboard Grid Stats */
        .dashboard-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 24px;
            margin-bottom: 48px;
        }}

        .stat-card {{
            padding: 24px;
            display: flex;
            align-items: center;
            gap: 20px;
            background: rgba(255, 255, 255, 0.02);
            border-radius: 24px;
            border: 1px solid var(--glass-border);
            transition: transform 0.2s;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }}

        .stat-card:hover {{
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.1);
            transform: translateY(-5px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
        }}

        .stat-icon {{
            width: 56px;
            height: 56px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            flex-shrink: 0;
            transition: all 0.2s;
            position: relative;
        }}

        .stat-card:hover .stat-icon {{
            transform: scale(1.1) rotate(5deg);
        }}

        .stat-info {{
            flex: 1;
            min-width: 0;
        }}

        .stat-label {{
            font-size: 10px;
            font-weight: 800;
            color: rgba(255, 255, 255, 0.4);
            text-transform: uppercase;
            letter-spacing: 1.2px;
            margin-bottom: 4px;
        }}

        .stat-value {{
            font-size: 26px;
            font-weight: 800;
            color: #FFFFFF;
            margin: 0;
            letter-spacing: -0.5px;
            line-height: 1.2;
        }}

        .stat-change {{
            font-size: 11px;
            font-weight: 600;
            margin-top: 4px;
            color: rgba(255, 255, 255, 0.3);
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        /* Buttons & Actions */
        button, .btn, .btn-glass, .btn-primary-glow, .btn-secondary-glass, .primary-btn, .secondary-btn, .btn-super {{
            border-radius: 12px !important;
            padding: 10px 16px !important;
            cursor: pointer !important;
            transition: all 0.2s ease !important;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            font-weight: 600;
            font-size: 14px;
            border: none;
        }}
        
        button:hover:not(:disabled), .btn:hover:not(:disabled), .btn-glass:hover:not(:disabled) {{
            transform: scale(1.03) !important;
        }}

        .btn-primary-glow, .primary-btn, .btn-super {{
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink)) !important;
            color: #FFFFFF !important;
            box-shadow: 0 4px 15px rgba(187, 134, 252, 0.3) !important;
        }}

        .btn-secondary-glass, .btn-glass, .secondary-btn {{
            background: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid var(--glass-border) !important;
            color: #ffffff !important;
        }}

        .icon-btn {{
            width: 40px !important;
            height: 40px !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            border-radius: 10px !important;
            flex-shrink: 0;
        }}

        .user-pill {{
            display: flex;
            align-items: center;
            gap: 14px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--glass-border);
            padding: 6px 6px 6px 16px;
            border-radius: 20px;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            cursor: pointer;
        }}

        .user-pill:hover {{
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(255, 255, 255, 0.15);
            transform: translateY(-2px);
        }}

        .user-name {{
            font-size: 14px;
            font-weight: 700;
            color: #FFFFFF;
            display: block;
        }}

        .user-role {{
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            display: block;
        }}

        .user-avatar {{
            width: 38px;
            height: 38px;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink));
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            color: white;
            font-size: 14px;
            box-shadow: 0 8px 16px rgba(79, 70, 229, 0.2);
        }}

        .logout-icon {{
            width: 36px;
            height: 36px;
            background: rgba(239, 68, 68, 0.1);
            color: var(--danger);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
            transition: all 0.3s;
            text-decoration: none !important;
        }}

        .logout-icon:hover {{
            background: var(--danger);
            color: white;
            transform: scale(1.05);
        }}
    </style>
    <style>
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
        }}
        
        .card-title {{
            font-size: 20px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.5px;
        }}
        
        h1, h2, h3, h4, h5, h6, .card-title, .modal-title {{
            color: #ffffff !important;
            font-weight: 800 !important;
            letter-spacing: -0.5px !important;
        }}
        
        .text-muted, .small.text-muted {{
            color: rgba(255, 255, 255, 0.65) !important;
            font-weight: 500;
        }}
        
        ::placeholder {{
            color: rgba(255, 255, 255, 0.45) !important;
        }}
        
        select option {{
            background: #0b0b0f !important;
            color: #ffffff !important;
        }}
        
        .form-check-input {{
            background-color: rgba(255, 255, 255, 0.08) !important;
            border-color: rgba(255, 255, 255, 0.18) !important;
            box-shadow: none !important;
        }}
        
        .form-check-input:checked {{
            background-color: rgba(175, 133, 255, 0.85) !important;
            border-color: rgba(175, 133, 255, 0.85) !important;
        }}
        
        .integration-selector {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
            gap: 12px;
            max-height: 300px;
            overflow-y: auto;
            padding: 12px;
            background: rgba(255, 255, 255, 0.015);
            border-radius: 20px;
        }}
        
        .integration-selector::-webkit-scrollbar {{
            width: 4px;
        }}
        
        .integration-selector::-webkit-scrollbar-thumb {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }}

        .integration-item {{
            display: block;
        }}
        
        @media (min-width: 768px) {{
            .integration-selector {{
                justify-content: flex-start;
            }}
        }}
        
        .integration-pill {{
            min-width: 110px;
            width: 100%;
            height: 74px;
            background: rgba(255,255,255,0.02);
            border: 0.5px solid var(--glass-border);
            border-radius: 26px;
            padding: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            user-select: none;
            position: relative;
            text-align: center;
            overflow: hidden;
            max-width: 100%;
        }}
        
        .integration-pill:hover {{
            background: rgba(255,255,255,0.05);
            transform: translateY(-2px);
        }}
        
        .integration-pill-text {{
            font-weight: 900;
            font-size: 11px;
            letter-spacing: 0.6px;
            color: rgba(255,255,255,0.88);
            text-transform: uppercase;
            line-height: 1.15;
            white-space: normal;
        }}

        .integration-pill-tag {{
            position: absolute;
            left: 50%;
            bottom: 10px;
            transform: translateX(-50%);
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            padding: 4px 8px;
            border-radius: 999px;
            background: rgba(255,255,255,0.05);
            border: 0.5px solid rgba(255,255,255,0.12);
            color: rgba(255,255,255,0.55);
        }}

        .integration-pill.disabled {{
            opacity: 0.45;
            cursor: not-allowed;
            transform: none !important;
        }}

        .integration-pill.disabled:hover {{
            background: rgba(255,255,255,0.02);
            transform: none;
        }}
        
        .btn-check:checked + .integration-pill {{
            background: rgba(157, 78, 221, 0.15);
            border-color: rgba(157, 78, 221, 0.5);
            box-shadow: 0 16px 40px rgba(157, 78, 221, 0.2);
        }}
        
        .btn-check:checked + .integration-pill::after {{
            content: "\\f00c";
            font-family: "Font Awesome 6 Free";
            font-weight: 900;
            position: absolute;
            top: 10px;
            right: 10px;
            width: 22px;
            height: 22px;
            border-radius: 10px;
            background: rgba(157, 78, 221, 0.9);
            color: #ffffff;
            line-height: 22px;
            text-align: center;
            box-shadow: 0 10px 20px rgba(157, 78, 221, 0.3);
        }}
        
        /* Tables */
        /* Tables iOS 26 */
        .table-responsive {{
            border-radius: 20px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            margin-bottom: 0;
            width: 100%;
            min-width: 0;
        }}

        .table-responsive::-webkit-scrollbar {{
            height: 4px;
        }}

        .table-responsive::-webkit-scrollbar-thumb {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }}

        .table-responsive table {{
            min-width: 100%;
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 12px;
        }}

        .glass-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 12px;
            min-width: 0;
        }}
        
        .glass-table th {{
            padding: 12px 20px;
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(255, 255, 255, 0.35);
            border: none;
            white-space: normal;
            word-break: break-word;
            min-width: 0;
        }}
        
        .glass-table tr {{
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        
        .glass-table td {{
            padding: 22px 24px;
            background: rgba(255, 255, 255, 0.02);
            border-top: 0.5px solid var(--glass-border);
            border-bottom: 0.5px solid var(--glass-border);
            vertical-align: middle;
            color: rgba(255, 255, 255, 0.9);
            font-size: 14px;
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: normal;
            word-break: break-word;
            min-width: 0;
            overflow-wrap: anywhere;
        }}
        
        .glass-table td:first-child {{
            border-left: 0.5px solid var(--glass-border);
            border-top-left-radius: 22px;
            border-bottom-left-radius: 22px;
        }}

        .glass-table td:last-child {{
            border-right: 0.5px solid var(--glass-border);
            border-top-right-radius: 22px;
            border-bottom-right-radius: 22px;
        }}
        
        .glass-table tr:hover td {{
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.12);
        }}
        
        .glass-table tr:hover {{
            transform: scale(1.008) translateY(-3px);
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
        }}
        
        /* Forms iOS 26 */
        .glass-input, .form-control, .form-select {{
            width: 100%;
            padding: 12px 16px !important;
            background: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 12px !important;
            color: #ffffff !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            outline: none !important;
            transition: all 0.25s ease-in-out !important;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
            word-break: break-word !important;
            overflow-wrap: break-word !important;
            min-width: 0 !important;
            max-width: 100% !important;
        }}
        
        input[type="date"], input[type="time"] {{
            color-scheme: dark;
        }}
        
        input[type="date"]::-webkit-calendar-picker-indicator,
        input[type="time"]::-webkit-calendar-picker-indicator {{
            filter: invert(1) opacity(0.75);
        }}
        
        .chat-list-item {{
            width: 100%;
            background: rgba(255, 255, 255, 0.02);
            border: 0.5px solid var(--glass-border);
            border-radius: 18px;
            padding: 14px 16px;
            color: #ffffff;
            cursor: pointer;
            transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            text-align: left;
        }}
        
        .chat-list-item:hover {{
            background: rgba(255, 255, 255, 0.05);
            transform: translateY(-2px);
        }}
        
        .chat-list-item.active {{
            border-color: rgba(175,133,255,0.45);
            background: rgba(175,133,255,0.08);
        }}
        
        .chat-header {{
            background: rgba(255,255,255,0.02);
            border-bottom: 0.5px solid var(--glass-border);
        }}
        
        .chat-box {{
            background: rgba(255,255,255,0.01);
        }}
        
        .chat-input-bar {{
            background: rgba(255,255,255,0.02);
            border-top: 0.5px solid var(--glass-border);
        }}
        
        .chat-bubble {{
            max-width: 78%;
            padding: 12px 14px;
            border-radius: 18px;
            border: 0.5px solid var(--glass-border);
            backdrop-filter: blur(18px) saturate(180%);
            -webkit-backdrop-filter: blur(18px) saturate(180%);
            color: rgba(255,255,255,0.92);
            font-size: 13px;
            line-height: 1.45;
        }}
        
        .chat-bubble.assistant {{
            background: rgba(157, 78, 221, 0.15);
            border-color: rgba(157, 78, 221, 0.3);
        }}
        
        .chat-bubble.user {{
            background: rgba(255, 255, 255, 0.05);
        }}
        
        .glass-input:focus, .form-control:focus, .form-select:focus {{
            background: rgba(255, 255, 255, 0.08) !important;
            border-color: var(--accent-primary) !important;
            box-shadow: 0 0 0 3px rgba(187, 134, 252, 0.2) !important;
        }}
        
        .form-label, label {{
            color: rgba(255, 255, 255, 0.8) !important;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: block;
            padding-left: 4px;
            word-break: break-word !important;
            max-width: 100%;
        }}

        /* Modals iOS 26 */
        .modal {{
            z-index: 1055 !important;
            background: rgba(10, 10, 15, 0.95) !important; /* ВАЖНО: прибираємо blur для усунення лагів FPS */
            backdrop-filter: none !important;
        }}
        .modal-content {{
            background: #1e1e2f !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 12px !important;
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.8) !important;
            pointer-events: auto !important;
            z-index: 1056 !important;
            padding: 16px !important;
        }}
        
        .modal-header {{
            border-bottom: 0.5px solid var(--glass-border) !important;
            padding: 32px 32px 24px !important;
        }}
        
        .modal-body {{
            padding: 32px !important;
        }}
        
        .modal-footer {{
            border-top: 0.5px solid var(--glass-border) !important;
            padding: 24px 32px 32px !important;
        }}
        
        .modal-backdrop {{
            display: none !important; /* УБИВАЕТ БАГ БЕСКОНЕЧНЫХ ПЕРЕКРЫТИЙ И ЛАГОВ! */
        }}

        /* Badges */
        .badge {{
            padding: 8px 14px !important;
            border-radius: 12px !important;
            font-weight: 800 !important;
            font-size: 11px !important;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        }}
        
        .bg-success.bg-opacity-10, .bg-success.bg-opacity-20 {{ background: rgba(52, 211, 153, 0.15) !important; color: #34d399 !important; border: 0.5px solid rgba(52, 211, 153, 0.2); }}
        .bg-primary.bg-opacity-10, .bg-primary.bg-opacity-20 {{ background: rgba(96, 165, 250, 0.15) !important; color: #60a5fa !important; border: 0.5px solid rgba(96, 165, 250, 0.2); }}
        .bg-danger.bg-opacity-10, .bg-danger.bg-opacity-20 {{ background: rgba(248, 113, 113, 0.15) !important; color: #f87171 !important; border: 0.5px solid rgba(248, 113, 113, 0.2); }}

        .badge.bg-secondary {{
            background: rgba(255, 255, 255, 0.1) !important;
            color: rgba(255, 255, 255, 0.7) !important;
            border: 0.5px solid rgba(255, 255, 255, 0.2);
        }}

        /* Custom Scrollbar */
        ::-webkit-scrollbar {{ width: 6px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: rgba(255, 255, 255, 0.1); border-radius: 10px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: rgba(255, 255, 255, 0.2); }}

        /* Animations */
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(15px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .main-content > * {{ animation: fadeIn 0.8s cubic-bezier(0.16, 1, 0.3, 1) both; }}

        .app-container {{
            display: flex;
            min-height: 100vh;
            width: 100%;
            gap: 12px;
            padding: 12px;
        }}

        /* Custom Calendar Grid */
        .custom-calendar {{
            background: rgba(255, 255, 255, 0.01);
            backdrop-filter: blur(var(--blur));
            border: 0.5px solid var(--glass-border);
            border-radius: 32px;
            padding: 32px;
        }}
        
        .calendar-month-year {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
        }}
        
        .calendar-nav button {{
            background: rgba(255, 255, 255, 0.03);
            border: 0.5px solid var(--glass-border);
            color: white;
            width: 40px;
            height: 40px;
            border-radius: 12px;
            transition: all 0.3s;
        }}
        
        .calendar-nav button:hover {{
            background: rgba(255, 255, 255, 0.08);
            border-color: var(--accent-primary);
        }}
        
        .weekdays {{
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            text-align: center;
            margin-bottom: 16px;
        }}
        
        .weekday {{
            font-size: 11px;
            font-weight: 800;
            color: rgba(255, 255, 255, 0.3);
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .days-grid {{
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 8px;
        }}
        
        canvas {{
            max-width: 100% !important;
            height: auto !important;
        }}
        
        .day {{
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 15px;
            border-radius: 16px;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            color: rgba(255, 255, 255, 0.8);
        }}
        
        .day:hover {{
            background: rgba(255, 255, 255, 0.05);
            transform: scale(1.05);
            color: #ffffff;
        }}
        
        .day.today {{
            background: var(--accent-primary);
            color: white;
            box-shadow: 0 10px 20px rgba(175, 133, 255, 0.3);
        }}
        
        .day.has-event::after {{
            content: '';
            position: absolute;
            bottom: 6px;
            width: 4px;
            height: 4px;
            background: var(--accent-pink);
            border-radius: 50%;
        }}
        
        .day.selected-day {{
            border: 1.5px solid var(--accent-primary);
            background: rgba(175, 133, 255, 0.1);
        }}
        
        .day.other-month {{
            opacity: 0.15;
        }}

        /* Top Clients List */
        .client-item {{
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 16px;
            border-radius: 20px;
            transition: all 0.3s;
            cursor: pointer;
        }}
        
        .client-item:hover {{
            background: rgba(255, 255, 255, 0.03);
        }}
        
        .client-avatar {{
            width: 48px;
            height: 48px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 14px;
            color: white;
        }}
        
        .client-avatar.vip {{ background: linear-gradient(135deg, #f59e0b, #d97706); }}
        .client-avatar.regular {{ background: linear-gradient(135deg, #6366f1, #4f46e5); }}
        .client-avatar.new {{ background: linear-gradient(135deg, #10b981, #059669); }}
        
        .client-info .client-name {{ font-weight: 700; font-size: 14px; color: #ffffff; margin-bottom: 2px; }}
        .client-info .client-meta {{ font-size: 11px; color: rgba(255, 255, 255, 0.4); font-weight: 600; }}
        
        .client-badge {{
            margin-left: auto;
            font-size: 9px;
            font-weight: 800;
            padding: 4px 8px;
            border-radius: 8px;
            text-transform: uppercase;
        }}
        
        .client-badge.vip {{ background: rgba(245, 158, 11, 0.1); color: #f59e0b; }}
        .client-badge.regular {{ background: rgba(99, 102, 241, 0.1); color: #6366f1; }}
        .client-badge.new {{ background: rgba(16, 185, 129, 0.1); color: #10b981; }}

        @media (min-width: 1200px) {{
            body:not(.sidebar-hidden) .sidebar-open-btn {{
                display: none !important;
            }}
        }}

        /* 📱 ЧИСТА ТА СТАБІЛЬНА МОБІЛЬНА АДАПТАЦІЯ */
        @media (max-width: 1199px) {{
            .sidebar-toggle-btn {{ display: none !important; }}
            .sidebar {{ width: 100px; padding: 20px 10px; }}
            .sidebar-logo .logo-text {{ display: none; }}
            .sidebar-logo {{ justify-content: center; margin-bottom: 30px; }}
            .sidebar .nav-link {{ flex-direction: column; text-align: center; padding: 12px 5px; gap: 6px; margin-bottom: 10px; }}
            .sidebar .nav-link i {{ font-size: 22px; width: auto; margin: 0; }}
            .sidebar .nav-link span {{ font-size: 10px; display: block; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; max-width: 100%; line-height: 1.2; }}
            .sidebar .nav-link.active::before {{ display: none; }}
            .main-content {{ margin-left: 100px; padding: 30px 20px; }}
        }}

        @media (max-width: 767.98px) {{
            * {{
                box-sizing: border-box !important;
            }}

            html, body {{
                overflow-x: hidden !important;
                width: 100% !important;
                max-width: 100vw !important;
                margin: 0 !important;
                padding: 0 !important;
            }}

            body {{
                padding-bottom: 0 !important;
                background-attachment: scroll !important;
            }}

            .app-container {{
                display: block !important;
                padding: 0 !important;
                gap: 0 !important;
                width: 100% !important;
                max-width: 100vw !important;
                overflow-x: hidden !important;
            }}

            .sidebar {{
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                bottom: 0 !important;
                width: 280px !important;
                height: 100vh !important;
                flex-direction: column !important;
                justify-content: flex-start !important;
                align-items: stretch !important;
                padding: 30px 20px !important;
                background: #0C051A !important;
                border-right: 1px solid var(--glass-border) !important;
                z-index: 2000 !important;
                transform: translateX(-100%);
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }}

            .sidebar.mobile-open {{
                transform: translateX(0) !important;
            }}

            .sidebar-logo {{ display: flex !important; margin-bottom: 30px !important; }}
            .sidebar-logo .logo-text {{ display: block !important; }}
            .sidebar-toggle-btn {{ display: flex !important; margin-left: auto !important; }}

            .sidebar > div:last-child {{ display: block !important; margin-top: auto !important; }}

            .sidebar .nav-link {{
                flex: 0 0 auto !important;
                flex-direction: row !important;
                width: 100% !important;
                padding: 14px 18px !important;
                margin-bottom: 8px !important;
                border-radius: 16px !important;
                text-align: left !important;
            }}
            .sidebar .nav-link span {{
                display: inline-block !important;
                font-size: 15px !important;
            }}

            .main-content {{
                margin-left: 0 !important;
                padding: 20px 12px 40px !important;
                width: 100% !important;
                max-width: 100vw !important;
                overflow-x: hidden !important;
            }}

            .top-header {{
                display: flex !important;
                flex-direction: column !important;
                align-items: stretch !important;
                gap: 15px !important;
                margin-bottom: 25px !important;
                padding-bottom: 15px !important;
            }}

        .top-header > div[style], .top-header > div:not(.header-title-row) {{
                display: flex !important;
                flex-direction: column !important;
                align-items: stretch !important;
                gap: 12px !important;
                width: 100% !important;
            }}
        .header-title-row {{ width: 100% !important; }}

            .page-title {{
                font-size: 24px !important;
                text-align: left !important;
            }}

            .search-box {{
                width: 100% !important;
                max-width: 100% !important;
            }}

            .search-box input {{ width: 100% !important; }}

            .user-pill {{
                width: 100% !important;
                justify-content: space-between !important;
                padding: 8px 12px !important;
            }}

            .user-info {{ display: block !important; }}

            .dashboard-stats {{
                grid-template-columns: 1fr !important;
                gap: 12px !important;
                margin-bottom: 20px !important;
                width: 100% !important;
            }}

            .stat-card {{
                padding: 15px 12px !important;
                flex-direction: column !important;
                align-items: flex-start !important;
                gap: 12px !important;
                border-radius: 20px !important;
                width: 100% !important;
            }}

            .stat-icon {{
                width: 42px !important;
                height: 42px !important;
                font-size: 16px !important;
                margin: 0 !important;
            }}

            .stat-value {{ font-size: 18px !important; }}

            .glass-card, .custom-calendar {{
                padding: 15px !important;
                border-radius: 24px !important;
                margin-bottom: 16px !important;
                width: 100% !important;
                max-width: 100% !important;
                overflow: hidden !important;
            }}

            .table-responsive {{
                border-radius: 12px !important;
                margin: 0 !important;
                width: 100% !important;
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch !important;
                display: block !important;
                white-space: nowrap !important;
                min-width: 0 !important;
            }}

            .table-responsive table {{
                width: auto !important;
                min-width: 100% !important;
                border-collapse: separate !important;
            }}

            .glass-table {{
                min-width: 100% !important;
                width: 100% !important;
                max-width: 100% !important;
                table-layout: auto !important;
            }}

            .glass-table th, .glass-table td {{
                padding: 12px 10px !important;
                font-size: 13px !important;
                white-space: nowrap !important;
                max-width: 100% !important;
                min-width: 0 !important;
            }}

            .modal {{
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
                margin: 0 !important;
                padding: 16px 0 !important;
                z-index: 1055 !important;
                overflow-x: hidden !important;
            }}

            .modal-dialog {{
                width: 95% !important;
                max-width: 540px !important;
                margin: 0 auto !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }}

            .modal-content {{
                width: 100% !important;
                max-width: 100% !important;
                max-height: 85vh !important;
                margin: 0 auto !important;
                border-radius: 24px !important;
                border: none !important;
                overflow: hidden !important;
            }}

            .modal-body {{
                max-height: calc(85vh - 140px) !important;
                overflow-y: auto !important;
                -webkit-overflow-scrolling: touch !important;
            }}

            .modal .d-flex {{
                flex-direction: column !important;
                gap: 12px !important;
            }}

            .modal .d-flex > * {{
                width: 100% !important;
                min-width: 0 !important;
            }}

            .modal .row {{
                width: 100% !important;
            }}

            .modal .col-md-6, .modal .col-lg-6, .modal .col-md-4, .modal .col-lg-4 {{
                width: 100% !important;
                max-width: 100% !important;
            }}

            input, textarea, select, .form-control, .form-select, .glass-input {{
                width: 100% !important;
                max-width: 100% !important;
                min-height: 44px !important;
                font-size: 16px !important;
                padding: 12px 16px !important;
                border-radius: 12px !important;
            }}

            button, .btn, .btn-glass, .btn-primary-glow {{
                border-radius: 12px !important;
                width: 100% !important;
                min-height: 44px !important;
                font-size: 14px !important;
                padding: 12px 20px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                margin: 0 !important;
            }}

            .nav-pills {{
                flex-wrap: wrap !important;
                gap: 8px !important;
                width: 100% !important;
            }}

            .nav-pills .nav-link {{
                flex: 1 1 auto !important;
                min-width: 120px !important;
            }}

            .integration-selector {{
                grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)) !important;
                gap: 8px !important;
            }}

            .integration-pill {{
                min-width: 100px !important;
                height: 60px !important;
                padding: 8px !important;
            }}

            .integration-pill-text {{ font-size: 10px !important; }}

            .calendar-month-year {{
                flex-direction: column !important;
                gap: 16px !important;
                text-align: center !important;
            }}

            .weekdays {{ font-size: 10px !important; }}
            .day {{ font-size: 14px !important; }}

            .chat-bubble {{
                max-width: 85% !important;
                font-size: 14px !important;
            }}

            .stat-card {{
                flex-direction: column !important;
                align-items: flex-start !important;
                gap: 12px !important;
                padding: 16px !important;
            }}

            .stat-icon {{
                width: 48px !important;
                height: 48px !important;
                font-size: 20px !important;
            }}

            .stat-value {{ font-size: 20px !important; }}

            .client-item {{
                flex-direction: column !important;
                align-items: flex-start !important;
                gap: 8px !important;
                padding: 12px !important;
            }}

            .client-avatar {{
                width: 40px !important;
                height: 40px !important;
                font-size: 12px !important;
            }}

            .modal-backdrop, .modal-backdrop.show {{
                width: 100vw !important;
                left: 0 !important;
                right: 0 !important;
            }}

            .modal-open {{
                overflow: hidden !important;
            }}

            .row {{
                margin-left: 0 !important;
                margin-right: 0 !important;
                width: 100% !important;
            }}

            .row > * {{
                padding-left: 0 !important;
                padding-right: 0 !important;
            }}
            
            button:disabled, .btn.disabled, .btn-primary-glow:disabled, .btn-glass:disabled {{
                opacity: 0.6 !important;
                pointer-events: none !important;
                cursor: not-allowed !important;
            }}

        .sidebar .nav-link span {{
                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
                display: block !important;
        }}

            .flex-grow-1, .min-w-0 {{ min-width: 0 !important; }}

            .app-container, .sidebar, .main-content, .glass-card, .modal, .modal-content {{
                overflow-x: hidden !important;
                max-width: 100vw !important;
            }}
        }}

        @media (max-width: 375px) {{
            .sidebar .nav-link {{ width: 65px !important; padding: 6px 2px !important; }}
            .page-title {{ font-size: 22px !important; }}
            .search-box input {{ font-size: 14px !important; }}
        }}

    </style></head>
    <body>
    <div class="app-container">
        <aside class="sidebar">
            <div class="sidebar-logo">
                <div class="logo-icon"><i class="fas fa-bolt"></i></div>
                <span class="logo-text">SafeOrbit</span>
                <button class="sidebar-toggle-btn" onclick="toggleSidebar()" title="Сховати панель"><i class="fas fa-chevron-left"></i></button>
            </div>
            <nav class="flex-grow-1">{menu_html}</nav>
            <div style="padding-top: 20px; border-top: 0.5px solid var(--glass-border); margin-top: 20px;">
                <a href="/logout" class="nav-link" style="color: #f87171;"><i class="fas fa-arrow-right-from-bracket"></i><span>Завершити сесію</span></a>
            </div>
        </aside>
        
        <main class="main-content">
            <div class="top-header">
                <div class="header-title-row">
                    <button class="btn-glass sidebar-open-btn" onclick="toggleSidebar()" style="padding: 10px 14px; border-radius: 12px; height: 44px; width: 44px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;"><i class="fas fa-bars"></i></button>
                    <h1 class="page-title text-truncate">{ 'Аналітика' if active in ['super', 'dash'] else ('Конфігурація' if active == 'set' else ('Склад' if active == 'fin' else (l['clients'] if active == 'cust' else ('AI Сервіс' if active == 'gen' else ('Інтелектуальний Асистент' if active == 'bot' else ('Журнал подій' if active == 'logs' else ('Комунікації' if active == 'chats' else ('Підтримка' if active == 'help' else 'Панель')))))))) }</h1>
                </div>
                <div style="display: flex; align-items: center; gap: 20px; flex-wrap: wrap;">
                    <div class="search-box">
                        <i class="fas fa-magnifying-glass"></i>
                        <input type="text" id="globalSearch" placeholder="Пошук..." autocomplete="off">
                        <div id="searchResults" class="search-results"></div>
                    </div>
                    {user_dropdown}
                </div>
            </div>
            {content}
            {scripts}
        </main>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function showToast(msg, type = 'success') {{
            Swal.fire({{
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000,
                icon: type,
                title: msg,
                background: 'rgba(20, 20, 25, 0.9)',
                color: '#fff',
                customClass: {{ popup: 'glass-card' }}
            }});
        }}
        
        const urlParams = new URLSearchParams(window.location.search);
        const msg = urlParams.get('msg');
        if (msg) {{
            const msgs = {{
                'added': 'Запис успішно додано!',
                'saved': 'Зміни збережено!',
                'deleted': 'Запис видалено!',
                'time_taken': 'Цей час вже зайнятий!',
                'sms_sent': 'Повідомлення відправлено!',
                'added_and_synced': 'Запис додано та синхронізовано!',
                'branch_added': 'Філію створено!',
                'branch_deleted': 'Філію видалено!',
                'login_exists': 'Такий логін вже існує!',
                'broadcast_sent': 'Розсилку відправлено!',
                'saved': 'Збережено!'
            }};
            showToast(msgs[msg] || msg);
            window.history.replaceState(null, null, window.location.pathname);
        }}
        
        // Search functionality
        const searchInput = document.getElementById('globalSearch');
        const searchResults = document.getElementById('searchResults');
        let searchTimeout;
        
        if (searchInput) {{
            searchInput.addEventListener('input', function() {{
                clearTimeout(searchTimeout);
                const query = this.value.trim();
                
                if (query.length < 2) {{
                    searchResults.classList.remove('active');
                    return;
                }}
                
                searchTimeout = setTimeout(() => performSearch(query), 300);
            }});
            
            searchInput.addEventListener('focus', function() {{
                if (this.value.trim().length >= 2) {{
                    searchResults.classList.add('active');
                }}
            }});
            
            document.addEventListener('click', function(e) {{
                if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {{
                    searchResults.classList.remove('active');
                }}
            }});
        }}
        
        async function performSearch(query) {{
            try {{
                const response = await fetch(`/api/search?q=${{encodeURIComponent(query)}}`);
                const data = await response.json();
                displaySearchResults(data.results);
            }} catch (err) {{
                console.error('Search error:', err);
            }}
        }}
        
        function displaySearchResults(results) {{
            if (!results || results.length === 0) {{
                searchResults.innerHTML = '<div class="search-result-item"><div class="search-result-title">Нічого не знайдено</div></div>';
                searchResults.classList.add('active');
                return;
            }}
            
            const html = results.map(r => `
                <div class="search-result-item" onclick="handleSearchResult('${{r.type}}', '${{r.id}}')">
                    <div class="search-result-title">${{r.title}}</div>
                    <div class="search-result-type">${{r.type === 'client' ? 'Гість' : r.type === 'appointment' ? 'Запис' : 'Сервіс'}}</div>
                </div>
            `).join('');
            
            searchResults.innerHTML = html;
            searchResults.classList.add('active');
        }}
        
        function handleSearchResult(type, id) {{
            if (type === 'client') {{
                window.location.href = `/admin/klienci?id=${{id}}`;
            }} else if (type === 'appointment') {{
                const row = document.querySelector(`[data-appt-id="${{id}}"]`);
                if (row) row.scrollIntoView({{behavior: 'smooth'}});
            }}
            searchResults.classList.remove('active');
        }}
        
        function toggleSidebar() {{
            if (window.innerWidth <= 767.98) {{
                document.querySelector('.sidebar').classList.toggle('mobile-open');
            }} else {{
                document.querySelector('.sidebar').classList.toggle('hidden');
                document.querySelector('.main-content').classList.toggle('expanded');
                document.body.classList.toggle('sidebar-hidden');
            }}
        }}
        
        document.addEventListener("DOMContentLoaded", async () => {{
            try {{
                const res = await fetch('/admin/api/unread-updates');
                const data = await res.json();
                if(data.count > 0) {{
                    const updLink = document.getElementById('menu-upd');
                    if(updLink) {{
                        updLink.innerHTML += `<span class="badge bg-danger rounded-pill ms-auto" style="font-size:10px; padding: 4px 8px;">${{data.count}}</span>`;
                    }}
                }}
            }} catch(e) {{}}
        }});

        // API Key UI functions
        function toggleApiKeyVisibility(inputId, button) {{
            const input = document.getElementById(inputId);
            if (input.type === "password") {{
                input.type = "text";
                button.innerHTML = '<i class="fas fa-eye-slash text-info"></i>';
                button.title = "Приховати ключ";
            }} else {{
                input.type = "password";
                button.innerHTML = '<i class="fas fa-eye text-info"></i>';
                button.title = "Показати ключ";
            }}
        }}

        function copyApiKey(inputId) {{
            const input = document.getElementById(inputId);
            input.type = "text"; // Temporarily show to copy
            input.select();
            document.execCommand("copy");
            input.type = "password"; // Hide again
            showToast('API ключ скопійовано!', 'success');
        }}
        
        // --- GLOBAL STATE MANAGEMENT & PERFORMANCE OPTIMIZATIONS ---
        document.addEventListener('DOMContentLoaded', () => {{
            const path = window.location.pathname;
            
            // 1. Відновлення активної вкладки (Запобігає скиданню після перезавантаження/збереження)
            const savedTab = localStorage.getItem('activeTab_' + path);
            if (savedTab) {{
                const tabBtn = document.querySelector(`[data-bs-target="${{savedTab}}"]`);
                if (tabBtn) {{
                    const tab = new bootstrap.Tab(tabBtn);
                    tab.show();
                }}
            }}

            // 2. Збереження стану вкладки
            const tabElements = document.querySelectorAll('button[data-bs-toggle="tab"], button[data-bs-toggle="pill"]');
            tabElements.forEach(el => {{
                el.addEventListener('shown.bs.tab', event => {{
                    const target = event.target.getAttribute('data-bs-target');
                    if(target) localStorage.setItem('activeTab_' + path, target);
                }});
            }});

            // 3. Глобальний Loading State для запобігання подвійних submit та зависань UI
            document.querySelectorAll('form').forEach(form => {{
                if(!form.hasAttribute('onsubmit')) {{
                    form.addEventListener('submit', function(e) {{
                        const btn = this.querySelector('button[type="submit"], button:not([type="button"])');
                        if (btn && !btn.disabled) {{
                            // Дозволяємо формі відправитись, але блокуємо UI
                            setTimeout(() => {{
                                btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Завантаження...';
                                btn.disabled = true;
                                btn.style.opacity = '0.7';
                                btn.style.pointerEvents = 'none';
                            }}, 10);
                        }}
                    }});
                }}
            }});
        }});
    </script>
    {scripts}</body></html>"""

def get_api_docs_html() -> str:
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SafeOrbit API Reference</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
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
