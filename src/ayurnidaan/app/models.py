"""ORM models. Health data minimisation is enforced here: no free-text address, exact
GPS is never stored (coordinates are rounded to 0.1 degree, about 11 km), and every
patient-linked row cascades on account erasure."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)  # patient | practitioner | admin
    full_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # practitioners only: State/NCISM registration number, verified by an admin
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    practitioner_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke refresh tokens
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    profile: Mapped[PatientProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    district: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lat_round: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon_round: Mapped[float | None] = mapped_column(Float, nullable=True)
    desha: Mapped[str | None] = mapped_column(String(16), nullable=True)
    climate: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prakriti_answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prakriti_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chronic_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    current_medicines: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Consent(Base):
    """Append-only consent ledger (DPDP Act 2023). Latest row per purpose is in force."""

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))  # care | research | location
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    practitioner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # draft -> submitted -> reviewed ; or emergency (red flag, never queued as routine)
    triage_level: Mapped[str] = mapped_column(String(16), default="routine")
    chief_complaint: Mapped[str | None] = mapped_column(String(300), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ritu: Mapped[str | None] = mapped_column(String(16), nullable=True)
    desha: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    reviews: Mapped[list[Review]] = relationship(
        back_populates="encounter", cascade="all, delete-orphan"
    )


class Review(Base):
    """A practitioner's verdict on an encounter - the label the learning loop trains on."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    encounter_id: Mapped[str] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    practitioner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(16))  # confirmed | revised | ruled_out | referred
    condition_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    condition_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    examination: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    encounter: Mapped[Encounter] = relationship(back_populates="reviews")


class ModelVersion(Base):
    """Learning-loop releases: which confirmed cases a model was fit on and how it scored."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    pack_version: Mapped[str] = mapped_column(String(32))
    n_cases: Mapped[int] = mapped_column(Integer)
    case_ids: Mapped[list] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LocationClimate(Base):
    """Cache of Open-Meteo climate lookups per 0.1-degree cell (no personal data)."""

    __tablename__ = "location_climate"

    cell: Mapped[str] = mapped_column(String(32), primary_key=True)  # "lat,lon" rounded
    annual_precip_mm: Mapped[float] = mapped_column(Float)
    mean_rh: Mapped[float] = mapped_column(Float)
    mean_temp_c: Mapped[float] = mapped_column(Float)
    desha: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
