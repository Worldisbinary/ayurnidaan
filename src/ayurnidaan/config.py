"""Runtime settings (env-overridable) and the typed source registry."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

Role = Literal[
    "patient_cohort", "assessment", "knowledge_base", "terminology", "epidemiology", "audit_only"
]


class Settings(BaseSettings):
    """All paths and secrets come from env vars prefixed ``AYUR_`` (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="AYUR_", env_file=".env", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data" / "raw"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"
    # PII-free bundle the production API runs on; committed to git (see clinical/knowledge.py)
    knowledge_dir: Path = PROJECT_ROOT / "knowledge_pack"
    sources_file: Path = PROJECT_ROOT / "configs" / "sources.yaml"
    # Salt for the one-way patient pseudonym. Override in every real deployment.
    pii_salt: str = "dev-only-salt-change-me"
    api_key: str | None = None  # when set, the analytics API requires X-API-Key
    seed: int = 42

    # --- clinical app (patients / practitioners) ---------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'ayurnidaan.db').as_posix()}"
    jwt_secret: str = "dev-only-jwt-secret-change-me-0123456789abcdef"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8081", "http://localhost:19006"]
    )
    rate_limit_per_minute: int = 120
    policy_version: str = "2026-10"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_geocode_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    geocode_country: str | None = "IN"  # ISO code; None searches worldwide
    bootstrap_admin_email: str | None = None  # first registration with this email -> admin

    def check_production(self) -> None:
        """Refuse to start in production with development secrets."""
        if self.environment != "production":
            return
        problems = []
        if self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32:
            problems.append("AYUR_JWT_SECRET must be a random string of >= 32 chars")
        if self.pii_salt.startswith("dev-only"):
            problems.append("AYUR_PII_SALT must be set")
        if self.database_url.startswith("sqlite"):
            problems.append("AYUR_DATABASE_URL must point at Postgres in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))

    @property
    def warehouse_path(self) -> Path:
        return self.artifacts_dir / "warehouse.duckdb"


class Source(BaseModel):
    """A dataset pulled from Kaggle (``kaggle`` slug) or a direct download (``url``)."""

    name: str
    kaggle: str | None = None
    url: str | None = None
    file: str
    sha256: str
    role: Role
    format: Literal["csv", "xml"] = "csv"
    label: str | None = None
    description: str = ""
    licence: str | None = None
    text_column: str | None = None
    entity_column: str | None = None

    @model_validator(mode="after")
    def _one_origin(self) -> Source:
        if bool(self.kaggle) == bool(self.url):
            raise ValueError(f"{self.name}: set exactly one of `kaggle` or `url`")
        return self

    @property
    def origin(self) -> str:
        return self.kaggle or self.url  # type: ignore[return-value]

    @property
    def slug_dir(self) -> str:
        return self.kaggle.replace("/", "__") if self.kaggle else f"url__{self.name}"

    def path(self, data_dir: Path) -> Path:
        return data_dir / self.slug_dir / self.file


class QualityGate(BaseModel):
    max_duplicate_rate: float = 0.05
    max_null_rate: float = 0.30
    min_text_uniqueness: float = 0.20
    noise_feature_alpha: float = 0.01
    max_noise_feature_share: float = 0.50


class Registry(BaseModel):
    sources: dict[str, Source]
    quality_gate: QualityGate = Field(default_factory=QualityGate)

    def by_role(self, role: Role) -> list[Source]:
        return [s for s in self.sources.values() if s.role == role]

    def __getitem__(self, name: str) -> Source:
        return self.sources[name]


def load_registry(path: Path) -> Registry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = {name: Source(name=name, **spec) for name, spec in raw["sources"].items()}
    return Registry(sources=sources, quality_gate=QualityGate(**raw.get("quality_gate", {})))


@lru_cache
def get_settings() -> Settings:
    return Settings()
