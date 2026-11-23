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


def charges(plan: str) -> tuple[Charge, ...]:
    prices = {
        "plan1": (("BUSINESS_SETUP", 13698), ("BUSINESS_MONTHLY", 16742)),
        "plan2": (("PRO_SETUP", 80668), ("PRO_MONTHLY", 1674)),
    }
    key = os.getenv("CREEM_API_KEY", "").strip()
    if not key or key.startswith("creem_test_") or os.getenv("CREEM_ENABLED") != "1":
        return ()
    configured = tuple(
        Charge(os.getenv(f"CREEM_{name}_PRODUCT_ID", "").strip(), cents, index == 1)
        for index, (name, cents) in enumerate(prices.get(plan, ()))
    )
    ids = {charge.product_id for charge in configured}
    if len(ids) != 2 or not all(re.fullmatch(r"prod_[A-Za-z0-9]+", value) for value in ids):
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


def is_paid(checkout: dict, checkout_id: str, request_id: str, product_id: str, cents: int) -> bool:
    product = checkout.get("product")
    if isinstance(product, dict):
        product = product.get("id")
    order = checkout.get("order")
    return (
        checkout.get("mode") == "prod"
        and checkout.get("id") == checkout_id
        and checkout.get("request_id") == request_id
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
