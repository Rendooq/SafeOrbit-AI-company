"""Campaign visits linked to the existing registration and verified billing records."""
from datetime import datetime, timedelta, timezone
import logging
import re
from uuid import uuid4

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from models import Business, CampaignVisit, CreemPayment
from utils.auth import AttemptLimiter


LANDINGS = {
    "/", "/taryfy", "/crm-dlia-saloniv", "/shablon-zhurnalu-zapysiv",
    "/rozbir-rozkladu", "/yak-zapovnyty-vilni-vikna-u-saloni", "/register",
}
SOURCES = {
    "linkedin", "facebook", "instagram", "spilno", "osyo", "product-radar", "product_radar",
    "g2", "capterra", "getapp", "software-advice", "telegram", "email", "referral",
    "partner", "youtube", "reddit",
}
VISIT_SESSION_KEY = "campaign_visit"
_TAG = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
_TOKEN = re.compile(r"[a-f0-9]{32}")
_PREVIEW = re.compile(r"bot\b|crawler|spider|facebookexternalhit|slack-imgproxy|headless|preview", re.I)
_VISITS = AttemptLimiter(limit=40, window=60)
logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def capture_visit(request, db):
    if request is None or "session" not in request.scope:
        return
    if request.method != "GET" or request.url.path not in LANDINGS:
        return
    session = request.session
    source = request.query_params.get("utm_source", "").strip().lower()
    if source not in SOURCES:
        return
    agent = request.headers.get("user-agent", "")
    if not agent or _PREVIEW.search(agent) or request.headers.get("purpose") == "prefetch":
        return
    campaign = request.query_params.get("utm_campaign", "").strip().lower()
    campaign = campaign if _TAG.fullmatch(campaign) else ""
    moment = utc_now()
    identity = [source, campaign, moment.date().isoformat()]
    previous = session.get(VISIT_SESSION_KEY)
    if isinstance(previous, dict) and previous.get("identity") == identity:
        return
    if not _VISITS.allow(request.client.host if request.client else "unknown"):
        return
    visit_id = uuid4().hex
    try:
        db.add(CampaignVisit(id=visit_id, source=source, campaign=campaign, visited_at=moment))
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.warning("Could not record campaign visit")
        return
    session[VISIT_SESSION_KEY] = {"id": visit_id, "identity": identity}
    logger.info("Campaign visit recorded: source=%s campaign=%s user_navigation=%s", source,
                campaign or "unspecified", request.headers.get("sec-fetch-user") == "?1")


def record_demo_open(visit):
    if not isinstance(visit, dict) or visit.get("demo_opened"):
        return
    identity = visit.get("identity")
    if not isinstance(identity, list) or len(identity) != 3:
        return
    source, campaign, _ = identity
    if not isinstance(source, str) or source not in SOURCES or not isinstance(campaign, str):
        return
    if campaign and not _TAG.fullmatch(campaign):
        return
    visit["demo_opened"] = True
    logger.info("Campaign demo opened: source=%s campaign=%s", source, campaign or "unspecified")


async def link_registration(request, business_id: int, db):
    reference = request.scope.get("session", {}).get(VISIT_SESSION_KEY)
    visit_id = reference.get("id", "") if isinstance(reference, dict) else ""
    if not isinstance(visit_id, str) or not _TOKEN.fullmatch(visit_id):
        return
    try:
        await db.execute(update(CampaignVisit).where(
            CampaignVisit.id == visit_id, CampaignVisit.business_id.is_(None),
            CampaignVisit.visited_at >= utc_now() - timedelta(days=30),
        ).values(business_id=business_id))
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.warning("Could not link registration to campaign visit")


async def report(db, days: int):
    checkout = exists(select(1).where(CreemPayment.business_id == Business.id, CreemPayment.checkout_id.is_not(None)))
    paid = exists(select(1).where(CreemPayment.business_id == Business.id, CreemPayment.recurring.is_(True),
                                  CreemPayment.paid.is_(True)))
    counts = await db.execute(
        select(
            CampaignVisit.source, CampaignVisit.campaign,
            func.count(CampaignVisit.id), func.count(Business.id),
            func.sum(case((checkout, 1), else_=0)), func.sum(case((paid, 1), else_=0)),
        )
        .outerjoin(Business, Business.id == CampaignVisit.business_id)
        .where(CampaignVisit.visited_at >= utc_now() - timedelta(days=days))
        .group_by(CampaignVisit.source, CampaignVisit.campaign)
        .order_by(func.count(CampaignVisit.id).desc(), CampaignVisit.source, CampaignVisit.campaign)
    )
    rows = counts.all()
    return rows, [sum(row[column] or 0 for row in rows) for column in range(2, 6)]
