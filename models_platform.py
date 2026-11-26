"""Tables for workspaces and the public booking marketplace."""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class WorkspaceLayout(Base):
    __tablename__ = "workspace_layouts"
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True)
    settings: Mapped[str] = mapped_column(Text)


class WorkspaceRecord(Base):
    __tablename__ = "workspace_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(160))
    data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkspaceAttachment(Base):
    __tablename__ = "workspace_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("workspace_records.id", ondelete="CASCADE"), index=True)
    media_type: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(160))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    city: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(String(1500))
    open_days: Mapped[str] = mapped_column(String(14))
    opens: Mapped[str] = mapped_column(String(5))
    closes: Mapped[str] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(48), default="Europe/Kyiv")


class MarketplaceClient(Base):
    __tablename__ = "marketplace_clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketplaceAvatar(Base):
    __tablename__ = "marketplace_avatars"
    client_id: Mapped[int] = mapped_column(ForeignKey("marketplace_clients.id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class MarketplaceVoucher(Base):
    __tablename__ = "marketplace_vouchers"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("marketplace_listings.business_id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_clients.id", ondelete="SET NULL"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"), unique=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    suffix: Mapped[str] = mapped_column(String(4))
    title: Mapped[str] = mapped_column(String(120))
    cents: Mapped[int] = mapped_column(Integer)
    expires_on: Mapped[date] = mapped_column(Date)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class MarketplacePhoto(Base):
    __tablename__ = "marketplace_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    caption: Mapped[str] = mapped_column(String(120))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class MarketplaceListingCategory(Base):
    __tablename__ = "marketplace_listing_categories"
    business_id: Mapped[int] = mapped_column(ForeignKey("marketplace_listings.business_id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str] = mapped_column(String(24), primary_key=True, index=True)


class MarketplaceFavorite(Base):
    __tablename__ = "marketplace_favorites"
    client_id: Mapped[int] = mapped_column(ForeignKey("marketplace_clients.id", ondelete="CASCADE"), primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("marketplace_listings.business_id", ondelete="CASCADE"), primary_key=True)


class MarketplaceVisit(Base):
    __tablename__ = "marketplace_visits"
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("marketplace_clients.id", ondelete="CASCADE"), index=True)
    duration: Mapped[int] = mapped_column(Integer)


class MarketplaceReview(Base):
    __tablename__ = "marketplace_reviews"
    appointment_id: Mapped[int] = mapped_column(ForeignKey("marketplace_visits.appointment_id", ondelete="CASCADE"), primary_key=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(1200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PhoneChallenge(Base):
    __tablename__ = "phone_challenges"
    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(28), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(43), unique=True)
    digest: Mapped[str] = mapped_column(String(64))
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class CheckoutProbe(Base):
    __tablename__ = "checkout_probes"
    __table_args__ = (UniqueConstraint("business_id", "domain", name="uq_checkout_probe_domain"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(253))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BookShare(Base):
    __tablename__ = "book_shares"
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True)
    token: Mapped[str] = mapped_column(String(43), unique=True)


class WorkspaceTable(Base):
    __tablename__ = "workspace_tables"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    fields: Mapped[str] = mapped_column(Text)


class WorkspaceTableRow(Base):
    __tablename__ = "workspace_table_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("workspace_tables.id", ondelete="CASCADE"), index=True)
    cells: Mapped[str] = mapped_column(Text)


class CreemWorkspaceSubscription(Base):
    __tablename__ = "creem_workspace_subscriptions"
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(96), unique=True)
    product_id: Mapped[str] = mapped_column(String(96))
    paid_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    newest_event: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(24), default="active")
    auto_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
