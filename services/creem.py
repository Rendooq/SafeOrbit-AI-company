import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class Charge:
    product_id: str
    cents: int
    recurring: bool


PLAN_PRICES = {
    "plan1": (("BUSINESS_SETUP", 0), ("BUSINESS_MONTHLY_V2", 990)),
    "plan2": (("PRO_SETUP", 80668), ("PRO_MONTHLY", 1674)),
    "commerce": (("COMMERCE_SETUP", 0), ("COMMERCE_MONTHLY", 1490)),
    "production": (("WORKSHOP_SETUP", 0), ("WORKSHOP_MONTHLY", 1290)),
    "custom": (("CUSTOM_SETUP", 0), ("CUSTOM_MONTHLY", 1980)),
}
ONLINE_TERMS_VERSION = "2026-11-26"
ONLINE_TERMS_PLANS = {"commerce", "production", "custom"}


def advertised(plan: str) -> tuple[Charge, ...]:
    return tuple(Charge("", cents, index == 1)
                 for index, (_, cents) in enumerate(PLAN_PRICES.get(plan, ())) if cents)


def agreement_path(plan: str) -> str:
    if plan == "plan1":
        return "/static/contract_business_monthly.pdf"
    if plan == "plan2":
        return "/static/contract_plan2.pdf"
    filename = os.getenv(f"CREEM_{plan.upper()}_TERMS_FILE", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,90}\.pdf", filename):
        return ""
    from pathlib import Path
    return f"/static/{filename}" if (Path(__file__).resolve().parents[1] / "static" / filename).is_file() else ""


def enabled() -> bool:
    key = os.getenv("CREEM_API_KEY", "").strip()
    return bool(key and not key.startswith("creem_test_") and os.getenv("CREEM_ENABLED") == "1")


def webhook_ready() -> bool:
    return bool(os.getenv("CREEM_WEBHOOK_SECRET", "").strip()) and enabled()


def offer_version(plan: str) -> str:
    if (plan in ONLINE_TERMS_PLANS and webhook_ready()
            and os.getenv("CREEM_ONLINE_TERMS_VERSION", "").strip() == ONLINE_TERMS_VERSION):
        return ONLINE_TERMS_VERSION
    return ""


def charges(plan: str) -> tuple[Charge, ...]:
    if not enabled():
        return ()
    if plan in ONLINE_TERMS_PLANS and not (offer_version(plan) or agreement_path(plan)):
        return ()
    configured = tuple(
        Charge(os.getenv(f"CREEM_{name}_PRODUCT_ID", "").strip(), cents, index == 1)
        for index, (name, cents) in enumerate(PLAN_PRICES.get(plan, ()))
        if cents
    )
    ids = {charge.product_id for charge in configured}
    if len(ids) != len(configured) or not all(re.fullmatch(r"prod_[A-Za-z0-9]+", value) for value in ids):
        return ()
    return configured


class CreemError(Exception):
    pass


async def api(method: str, resource: str, **kwargs) -> dict:
    headers = {"x-api-key": os.environ["CREEM_API_KEY"].strip()}
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.request(method, f"https://api.creem.io/v1/{resource}", headers=headers, **kwargs)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        raise CreemError(f"{method} {resource.split('/')[0]} returned HTTP {exc.response.status_code}") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise CreemError(f"{method} {resource.split('/')[0]} failed ({type(exc).__name__})") from exc
    if not isinstance(result, dict) or result.get("mode") != "prod":
        raise CreemError("Creem returned an invalid production object")
    return result


async def get_product(product_id: str) -> dict:
    if not re.fullmatch(r"prod_[A-Za-z0-9]+", product_id):
        raise CreemError("Invalid product reference")
    return await api("GET", f"products/{product_id}")


def checkout_url(value: object) -> str:
    if not isinstance(value, str):
        raise CreemError("Missing checkout URL")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise CreemError("Invalid checkout URL") from exc
    if (parsed.scheme != "https" or parsed.netloc not in {"checkout.creem.io", "creem.io", "www.creem.io"}
            or parsed.path.startswith("/test/") or not parsed.path.strip("/")):
        raise CreemError("Invalid production checkout URL")
    return value


def is_paid(checkout: dict, checkout_id: str, product_id: str, cents: int) -> bool:
    product = checkout.get("product")
    if isinstance(product, dict):
        product = product.get("id")
    order = checkout.get("order")
    return (
        checkout.get("mode") == "prod"
        and checkout.get("id") == checkout_id
        and checkout.get("status") == "completed"
        and product == product_id
        and isinstance(order, dict)
        and order.get("status") == "paid"
        and order.get("currency") == "EUR"
        and order.get("sub_total") == cents
        and type(order.get("amount_paid")) is int
        and type(order.get("amount_due")) is int
        and order["amount_paid"] >= order["amount_due"] >= cents
    )
