"""Cached, autoescaped server rendering; no frontend build or network dependency."""
import os
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from utils.request_security import protect_forms

ROOT = Path(__file__).resolve().parents[1]
environment = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=os.getenv("ENVIRONMENT", "").lower() not in {"production", "prod"},
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_template(name: str, **context) -> str:
    page = environment.get_template(name).render(**context)
    if "</head>" in page and "/static/v2/theme-init.js" not in page:
        # Final semantic layer after feature CSS; init runs before styles paint.
        page = page.replace("<head>", '<head><script src="/static/v2/theme-init.js?v=readability-2"></script>', 1)
        page = page.replace("</head>",
            '<link rel="stylesheet" href="/static/v2/theme.css?v=readability-2">'
            '<script src="/static/v2/theme.js?v=sale-locales2" defer></script></head>', 1)
    return protect_forms(page)


def login_html() -> str:
    return render_template("auth/login.html")
