import os
import ssl
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Global labels for business types
LABELS = {
    "barbershop": {"clients": "Профілі гостей", "masters": "Експерти", "services": "Сервіси", "new_appt": "Реєстрація візиту", "appts": "Історія активності", "master_single": "Експерт", "service_single": "Сервіс", "stats_today": "ВІЗИТІВ СЬОГОДНІ", "stats_month": "ВІЗИТІВ МІСЯЦЬ", "rev_month": "ДОХІД МІСЯЦЬ", "rev_total": "ДОХІД ВСЬОГО", "analytics_source": "Джерела записів", "analytics_services": "Популярність сервісів", "analytics_clients": "Топ-5 Гостей (LTV)"},
    "dentistry": {"clients": "Профілі пацієнтів", "masters": "Лікарі", "services": "Процедури", "new_appt": "Реєстрація візиту", "appts": "Історія активності", "master_single": "Лікар", "service_single": "Процедура", "stats_today": "ВІЗИТІВ СЬОГОДНІ", "stats_month": "ВІЗИТІВ МІСЯЦЬ", "rev_month": "ДОХІД МІСЯЦЬ", "rev_total": "ДОХІД ВСЬОГО", "analytics_source": "Джерела записів", "analytics_services": "Популярність процедур", "analytics_clients": "Топ-5 Пацієнтів (LTV)"},
    "medical": {"clients": "Профілі пацієнтів", "masters": "Лікарі", "services": "Сервіси", "new_appt": "Реєстрація візиту", "appts": "Історія активності", "master_single": "Лікар", "service_single": "Сервіс", "stats_today": "ВІЗИТІВ СЬОГОДНІ", "stats_month": "ВІЗИТІВ МІСЯЦЬ", "rev_month": "ДОХІД МІСЯЦЬ", "rev_total": "ДОХІД ВСЬОГО", "analytics_source": "Джерела записів", "analytics_services": "Популярність сервісів", "analytics_clients": "Топ-5 Пацієнтів (LTV)"},
    "fitness": {"clients": "Профілі гостей", "masters": "Експерти", "services": "Тренування", "new_appt": "Реєстрація візиту", "appts": "Історія активності", "master_single": "Експерт", "service_single": "Тренування", "stats_today": "ВІЗИТІВ СЬОГОДНІ", "stats_month": "ВІЗИТІВ МІСЯЦЬ", "rev_month": "ДОХІД МІСЯЦЬ", "rev_total": "ДОХІД ВСЬОГО", "analytics_source": "Джерела записів", "analytics_services": "Популярність тренувань", "analytics_clients": "Топ-5 Гостей (LTV)"},
    "retail": {"clients": "Профілі покупців", "masters": "Менеджери", "services": "Товари", "new_appt": "Реєстрація замовлення", "appts": "Історія активності", "master_single": "Менеджер", "service_single": "Товар", "stats_today": "ЗАМОВЛЕНЬ СЬОГОДНІ", "stats_month": "ЗАМОВЛЕНЬ МІСЯЦЬ", "rev_month": "ВИРУЧКА МІСЯЦЬ", "rev_total": "ВИРУЧКА ВСЬОГО", "analytics_source": "Джерела замовлень", "analytics_services": "Популярність товарів", "analytics_clients": "Топ-5 Покупців (LTV)"},
    "generic": {"clients": "Профілі гостей", "masters": "Експерти", "services": "Сервіси", "new_appt": "Реєстрація візиту", "appts": "Історія активності", "master_single": "Експерт", "service_single": "Сервіс", "stats_today": "ВІЗИТІВ СЬОГОДНІ", "stats_month": "ВІЗИТІВ МІСЯЦЬ", "rev_month": "ДОХІД МІСЯЦЬ", "rev_total": "ДОХІД ВСЬОГО", "analytics_source": "Джерела записів", "analytics_services": "Популярність сервісів", "analytics_clients": "Топ-5 Гостей (LTV)"},
}

BASE_LABELS = {
    "barbershop": {"clients": "Профілі гостей", "masters": "Експерти", "services": "Сервіси", "warehouse": "Склад"},
    "dentistry": {"clients": "Профілі пацієнтів", "masters": "Лікарі", "services": "Процедури", "warehouse": "Склад"},
    "medical": {"clients": "Профілі пацієнтів", "masters": "Лікарі", "services": "Сервіси", "warehouse": "Склад"},
    "fitness": {"clients": "Профілі гостей", "masters": "Експерти", "services": "Тренування", "warehouse": "Склад"},
    "retail": {"clients": "Профілі покупців", "masters": "Менеджери", "services": "Товари", "warehouse": "Склад"},
    "generic": {"clients": "Профілі гостей", "masters": "Експерти", "services": "Сервіси", "warehouse": "Склад"},
}

# --- Database Configuration ---

def _host_from_db_url(url: str) -> str:
    try:
        for prefix in ("postgresql+asyncpg://", "postgres://"):
            if url.startswith(prefix):
                u = "postgresql://" + url.split("://", 1)[1]
                return (urlparse(u).hostname or "").lower()
        if url.startswith("postgresql://"):
            return (urlparse(url).hostname or "").lower()
    except Exception:
        pass
    return ""


_LIBPQ_QUERY_KEYS_ASYNCPG_IGNORES = frozenset(
    {
        "channel_binding",  # libpq / Neon; asyncpg не приймає в connect()
        "sslmode",  # TLS задаємо через connect_args.ssl
    }
)


def _strip_asyncpg_incompatible_query_params(url: str) -> str:
    """Прибираємо libpq-параметри з query: asyncpg отримує ssl через connect_args, інакше TypeError."""
    low = url.lower()
    if not any(k in low for k in ("channel_binding", "sslmode")):
        return url
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        pairs = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in _LIBPQ_QUERY_KEYS_ASYNCPG_IGNORES
        ]
        new_q = urlencode(pairs)
        return urlunparse(parsed._replace(query=new_q))
    except Exception:
        return url


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url.split("://", 1)[0]:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return _strip_asyncpg_incompatible_query_params(url)


def asyncpg_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    host = _host_from_db_url(url)
    if host in ("localhost", "127.0.0.1", "::1") or not host:
        return {}
    if os.getenv("DATABASE_SSL_INSECURE", "").lower() in ("1", "true", "yes"):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = ssl.create_default_context()
    return {"ssl": ctx, "timeout": 60}


def _resolve_database_url() -> str:
    """Якщо DATABASE_URL не задано — локальний SQLite (app працює без Render). Для продакшену задайте DATABASE_URL."""
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        return _normalize_database_url(raw)
    return "sqlite+aiosqlite:///./local.db"


DATABASE_URL = _resolve_database_url()


def is_sqlite_db() -> bool:
    return DATABASE_URL.startswith("sqlite")

# --- API Keys and Secrets ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "SUPER_SECRET_KEY_PRO_999")
SUPERADMIN_TG_BOT_TOKEN = os.getenv("SUPERADMIN_TG_BOT_TOKEN", "")
SUPERADMIN_TG_CHAT_ID = os.getenv("SUPERADMIN_TG_CHAT_ID", "")
WEBHOOK_SIGNING_SECRET = os.getenv("WEBHOOK_SIGNING_SECRET", "a_very_secret_key_for_webhooks")

# --- Other Constants ---
DEFAULT_SMS_SENDER = "Service"
UA_TZ = pytz.timezone('Europe/Kyiv')