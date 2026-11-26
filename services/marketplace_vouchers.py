"""A voucher belongs to one merchant and can discount one active visit."""
import hashlib
import re
import secrets
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select

from models import Appointment
from models_platform import MarketplaceVoucher
from services.marketplace import now


def code_digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def normalize_code(value):
    code = re.sub(r"[-\s]", "", value).upper()
    return code if re.fullmatch(r"[A-F0-9]{20}", code) else ""


def new_code():
    raw = secrets.token_hex(10).upper()
    return "-".join(raw[i:i + 5] for i in range(0, len(raw), 5)), code_digest(raw), raw[-4:]


def available_vouchers(client_id, business_id, day):
    return (select(MarketplaceVoucher)
            .outerjoin(Appointment, Appointment.id == MarketplaceVoucher.appointment_id)
            .where(MarketplaceVoucher.client_id == client_id, MarketplaceVoucher.business_id == business_id,
                   MarketplaceVoucher.revoked.is_(False), MarketplaceVoucher.expires_on >= day,
                   or_(MarketplaceVoucher.appointment_id.is_(None), Appointment.id.is_(None),
                       Appointment.status == "cancelled")).order_by(MarketplaceVoucher.expires_on, MarketplaceVoucher.id))


def status(voucher, visit_status):
    if voucher.revoked:
        return "Скасовано"
    if visit_status == "completed":
        return "Використано"
    if visit_status and visit_status != "cancelled":
        return "Застосовано до візиту"
    if voucher.expires_on < now().date():
        return "Термін минув"
    return "Доступний" if voucher.client_id else "Не додано клієнтом"


def net_price(price, voucher):
    total = Decimal(str(price)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    return float(max(Decimal(0), total - Decimal(voucher.cents) / 100)) if voucher else float(total)
