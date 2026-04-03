import html
from models import User
from config import LABELS

def get_layout(content: str, user: User, active: str, scripts: str = ""):
    is_super = user.role == "superadmin"
    is_master = user.role == "master"
    
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
        if user.business and user.business.has_ai_bot:
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SafeOrbit CRM | Premium B2B</title>
    <link rel="icon" href="/static/favicon.png" type="image/png">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
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
            --blur: 40px;
        }}
        
        body {{
            font-family: 'Manrope', system-ui, -apple-system, sans-serif;
            background: var(--bg-primary);
            background-attachment: fixed;
            min-height: 100vh;
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
            backdrop-filter: blur(var(--blur));
            border-right: 1px solid var(--glass-border);
            padding: 40px 20px;
            position: fixed;
            height: 100vh;
            display: flex;
            flex-direction: column;
            z-index: 1000;
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
        }}
        
        .top-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 48px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--glass-border);
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
            backdrop-filter: blur(var(--blur)) saturate(180%); /* Stronger blur, saturation */
            border: 1px solid var(--glass-border);
            border-radius: 28px;
            padding: 32px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.3), inset 0 1px 1px rgba(255,255,255,0.08); /* Softer, layered shadow */
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
        }}
        
        .glass-card::after {{
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.02), transparent);
            transition: 0.6s;
        }}

        .glass-card:hover {{
            transform: translateY(-6px);
            border-color: rgba(255, 255, 255, 0.12);
            box-shadow: 0 20px 45px rgba(0, 0, 0, 0.45); /* Enhanced hover shadow */
        }}

        .glass-card:hover::after {{
            left: 100%;
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
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
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
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
        }}

        .stat-icon::after {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            border-radius: inherit;
            background: inherit;
            filter: blur(12px);
            opacity: 0.3;
            z-index: -1;
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
        .btn-glass {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--glass-border);
            color: #FFFFFF !important;
            padding: 10px 18px;
            border-radius: 14px;
            font-weight: 700;
            font-size: 13px;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: inline-flex;
            align-items: center;
            gap: 8px;
            text-decoration: none !important;
        }}

        .btn-glass:hover {{
            background: #FFFFFF;
            color: #000000 !important;
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
        }}

        .btn-glass i {{
            font-size: 14px;
        }}

        .btn-primary-glow {{
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-pink));
            border: none;
            color: white !important;
            border-radius: 16px;
            padding: 16px 32px;
            font-weight: 700;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 0 12px 30px rgba(157, 78, 221, 0.4);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            text-decoration: none !important;
        }}
        
        .btn-primary-glow:hover {{
            transform: translateY(-3px) scale(1.02);
            box-shadow: 0 18px 45px rgba(157, 78, 221, 0.55);
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
        }}
        
        .table-responsive::-webkit-scrollbar {{
            height: 4px;
        }}
        
        .table-responsive::-webkit-scrollbar-thumb {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }}

        .glass-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 12px;
        }}
        
        .glass-table th {{
            padding: 12px 20px;
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(255, 255, 255, 0.35);
            border: none;
            white-space: nowrap;
        }}
        
        .glass-table tr {{
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        
        .glass-table td {{
            padding: 18px 20px;
            background: rgba(255, 255, 255, 0.02);
            border-top: 1px solid var(--glass-border);
            border-bottom: 1px solid var(--glass-border);
            color: #FFFFFF;
            font-size: 14px;
        }}

        .glass-table td:first-child {{
            border-left: 1px solid var(--glass-border);
            border-radius: 16px 0 0 16px;
        }}

        .glass-table td:last-child {{
            border-right: 1px solid var(--glass-border);
            border-radius: 0 16px 16px 0;
        }}
        
        .glass-table tr:hover td {{
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.12);
        }}
            transform: scale(1.008) translateY(-3px);
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
        }}
        
        .glass-table td {{
            padding: 22px 24px;
            border-top: 0.5px solid var(--glass-border);
            border-bottom: 0.5px solid var(--glass-border);
            vertical-align: middle;
            color: rgba(255, 255, 255, 0.9);
            font-size: 14px;
            font-weight: 500;
            max-width: 250px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
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
        
        /* Forms iOS 26 */
        .glass-input, .form-control, .form-select {{
            width: 100%;
            padding: 12px 18px !important;
            background: rgba(255, 255, 255, 0.02) !important;
            backdrop-filter: blur(20px) saturate(180%);
            border: 0.5px solid var(--glass-border) !important;
            border-radius: 16px !important;
            color: #ffffff !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            outline: none !important;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.1);
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
            background: rgba(255, 255, 255, 0.04) !important;
            border-color: rgba(157, 78, 221, 0.5) !important;
            box-shadow: 0 0 30px rgba(157, 78, 221, 0.15), inset 0 1px 2px rgba(0,0,0,0.05) !important;
            transform: translateY(-1px);
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
        .modal-content {{
            background: rgba(20, 20, 25, 0.7) !important;
            backdrop-filter: blur(var(--blur)) saturate(180%) !important;
            -webkit-backdrop-filter: blur(var(--blur)) saturate(180%) !important;
            border: 0.5px solid var(--glass-border) !important;
            border-radius: 40px !important;
            box-shadow: 0 40px 100px rgba(0, 0, 0, 0.6) !important;
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

        /* Mobile Adaptation iOS 26 */
        @media (max-width: 991.98px) {{
            .app-container {{
                flex-direction: column;
                padding: 10px;
                gap: 12px;
            }}
            
            .sidebar {{
                width: 100% !important;
                min-width: 100% !important;
                height: auto !important;
                position: sticky !important;
                top: 0 !important;
                padding: 12px 16px !important;
                flex-direction: row !important;
                overflow-x: auto;
                border-radius: 20px !important;
                margin-bottom: 0;
                z-index: 1000;
                background: rgba(20, 20, 25, 0.9);
            }}
            
            .sidebar::-webkit-scrollbar {{
                display: none;
            }}
            
            .sidebar-logo {{
                margin-bottom: 0 !important;
                margin-right: 20px;
                padding: 0 !important;
                gap: 10px;
            }}
            
            .logo-icon {{
                width: 36px;
                height: 36px;
                font-size: 16px;
            }}
            
            .logo-text {{
                font-size: 18px;
                display: none;
            }}
            
            .sidebar .nav-link {{
                margin-bottom: 0 !important;
                margin-right: 6px;
                padding: 10px 14px !important;
                font-size: 13px;
                white-space: nowrap;
                gap: 8px;
            }}
            
            .sidebar .nav-link i {{
                font-size: 16px;
                width: auto;
            }}
            
            .main-content {{
                padding: 0 !important;
                gap: 12px;
            }}
            
            .top-header {{
                padding: 16px 20px !important;
                border-radius: 20px !important;
                margin-bottom: 12px;
                flex-direction: column;
                align-items: stretch !important;
                gap: 16px;
            }}
            
            .search-box {{
                width: 100% !important;
            }}
            
            .user-pill {{
                width: 100%;
                justify-content: flex-start;
                padding: 4px 4px 4px 12px;
            }}
            
            .user-info {{
                flex: 1;
            }}
            
            .dashboard-stats {{
                grid-template-columns: repeat(2, 1fr) !important;
                gap: 10px !important;
                margin-bottom: 12px;
            }}
            
            .stat-card {{
                padding: 12px 14px !important;
                min-height: 80px;
            }}
            
            .stat-icon {{
                width: 44px !important;
                height: 44px !important;
                font-size: 18px !important;
                border-radius: 14px;
            }}
            
            .stat-info .stat-value {{
                font-size: 18px;
            }}
            
            .glass-card, .custom-calendar {{
                padding: 16px !important;
                border-radius: 20px !important;
            }}
            
            .card-header {{
                margin-bottom: 20px;
            }}
            
            .card-title {{
                font-size: 18px;
            }}
            
            .integration-selector {{
                grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)) !important;
                gap: 8px !important;
            }}
            
            .integration-pill {{
                width: 100% !important;
                height: 64px !important;
                border-radius: 18px !important;
                padding: 8px !important;
            }}
            
            .integration-pill-text {{
                font-size: 9px !important;
            }}
            
            .modal-content {{
                border-radius: 24px !important;
            }}
            
            .modal-header, .modal-body, .modal-footer {{
                padding: 20px !important;
            }}
            
            .btn-glass, .btn-primary-glow {{
                padding: 10px 16px !important;
                font-size: 13px !important;
                border-radius: 14px !important;
            }}
        }}
        
        @media (max-width: 575.98px) {{
            .dashboard-stats {{
                grid-template-columns: 1fr !important;
            }}
            
            .sidebar-logo span {{
                display: none;
            }}
        }}
    </style></head>
    <body>
    <div class="app-container">
        <aside class="sidebar">
            <div class="sidebar-logo">
                <div class="logo-icon"><i class="fas fa-bolt"></i></div>
                <span class="logo-text">SafeOrbit</span>
            </div>
            <nav class="flex-grow-1">{menu_html}</nav>
            <div style="padding-top: 20px; border-top: 0.5px solid var(--glass-border); margin-top: 20px;">
                <a href="/logout" class="nav-link" style="color: #f87171;"><i class="fas fa-arrow-right-from-bracket"></i><span>Завершити сесію</span></a>
            </div>
        </aside>
        
        <main class="main-content">
            <div class="top-header">
                <div>
                    <h1 class="page-title">{ 'Аналітика' if active in ['super', 'dash'] else ('Конфігурація' if active == 'set' else ('Склад' if active == 'fin' else (l['clients'] if active == 'cust' else ('AI Сервіс' if active == 'gen' else ('Інтелектуальний Асистент' if active == 'bot' else ('Журнал подій' if active == 'logs' else ('Комунікації' if active == 'chats' else ('Підтримка' if active == 'help' else 'Панель')))))))) }</h1>
                </div>
                <div style="display: flex; align-items: center; gap: 20px;">
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
    </script>
    {scripts}</body></html>"""
