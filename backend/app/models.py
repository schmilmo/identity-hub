"""SQLAlchemy ORM models.

Tenancy note: for this POC, 1 user == 1 tenant. Every tenant-scoped row
carries user_id, and all queries filter on it. The schema is intentionally
shaped so a separate `tenant_id` (org with many users) could be introduced
later without restructuring.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    # A user authenticates either by local password OR via an IdP (idp_subject),
    # never relevant to the other. Exactly one is populated per user.
    __table_args__ = (UniqueConstraint("idp_issuer", "idp_subject"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Null for IdP-provisioned users (no local password).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set for OIDC users: the IdP's issuer + stable subject claim.
    idp_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idp_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    jira_connection: Mapped["JiraConnection | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class JiraConnection(Base):
    """A user's credential *to* Jira. Token is AES-GCM encrypted at rest."""

    __tablename__ = "jira_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    site_url: Mapped[str] = mapped_column(String(255))  # e.g. acme.atlassian.net
    jira_email: Mapped[str] = mapped_column(String(320))
    api_token_ciphertext: Mapped[bytes] = mapped_column()  # AES-GCM ciphertext
    api_token_nonce: Mapped[bytes] = mapped_column()  # per-record nonce
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="jira_connection")


class ApiKey(Base):
    """An IdentityHub-issued key used by external systems to call /api/v1.

    Plaintext is shown to the user exactly once at creation; we persist only
    a SHA-256 hash plus a short prefix for identification in the UI.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Session(Base):
    """Server-side session. The cookie holds the opaque id; deleting the row
    revokes the session immediately."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # opaque token
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
