"""
Customer credentials, sessions and the security audit trail. These tables
belong to the BFF only; the API identifies customers solely by the `sub`
(customer id) in the token the BFF signs, and never sees these tables.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime.datetime:
    # naive UTC: identical behaviour on SQLite (no tz support) and Postgres "timestamp"
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "auth_customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)  # stored lower-cased
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)                    # Argon2id, never plaintext
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")        # customer | staff
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")        # active | disabled
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    email_verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # TOTP: secrets are encrypted with the BFF data key (security.encrypt), never stored in clear.
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # during setup
    mfa_enabled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    mfa_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # last accepted 30 s step: no code replay

    @property
    def mfa_enabled(self) -> bool:
        return self.mfa_secret_enc is not None


class Session(Base):
    """Server-side session. The browser holds only a random token in an HttpOnly
    cookie; this table stores its SHA-256, so a DB leak does not leak live sessions."""
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(cookie token) hex
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_customers.id"), index=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)          # absolute limit
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class AuthToken(Base):
    """Single-use, expiring tokens sent by email (verify_email, password_reset) or
    handed out between the password and MFA steps of a login (mfa_login).
    Like sessions, only the SHA-256 of the token is stored."""
    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_customers.id"), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RecoveryCode(Base):
    """One-time MFA recovery codes, stored as keyed hashes (HMAC with the data key)."""
    __tablename__ = "auth_recovery_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_customers.id"), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class AccessKey(Base):
    """Personal access key a customer creates for an AI assistant (MCP client).
    Shown once; only the SHA-256 is stored. The MCP server checks every key with
    the BFF (/bff/internal/introspect), so revocation takes effect immediately."""
    __tablename__ = "auth_access_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)          # sha256(key)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_customers.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)        # e.g. fea_mcp_AbCd, for recognising it
    scopes: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class AuthEvent(Base):
    """Append-only security log: registrations, logins (ok/failed/locked), logouts,
    password changes, session revocations."""
    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    event: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
