"""Application settings, loaded from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FundTrace"
    environment: str = "local"  # local | test | cloud

    # Database. Local default is SQLite; Cloud Run uses Cloud SQL for MySQL, e.g.
    # mysql+pymysql://user:pass@/fundtrace?unix_socket=/cloudsql/PROJECT:REGION:INSTANCE
    database_url: str = "sqlite:///./fundtrace.db"
    seed_on_start: bool = True

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 480
    cookie_secure: bool = False
    demo_password: str = "Investigate@2026"
    show_demo_credentials: bool = True  # synthetic public demo: judges need to log in
    firebase_project_id: str | None = None  # enables Firebase ID-token login when set

    # Evidence storage: "local" (./uploads) or "gcs"
    storage_backend: str = "local"
    local_upload_dir: str = "./uploads"
    gcs_bucket: str | None = None
    max_upload_bytes: int = 5 * 1024 * 1024
    evidence_retention_days: int = 365

    # Vertex AI / Gemini
    gcp_project: str | None = None
    gcp_location: str = "asia-south1"
    gemini_location: str = "global"  # Vertex AI endpoint for Gemini ("global" or a region)
    llm_enabled: bool = True
    # Comma-separated fallback chains: the first model that responds is used.
    gemini_fast_models: str = "gemini-3.8-flash,gemini-2.5-flash"
    gemini_pro_models: str = "gemini-3.1-pro-preview,gemini-3.8-flash"
    llm_timeout_seconds: float = 60.0  # fast tier (explore, evidence, judge, copilot)
    llm_pro_timeout_seconds: float = 150.0  # report drafting; on timeout falls back to the next model in the chain
    llm_daily_budget_usd: float = 20.0
    llm_case_budget_usd: float = 1.0
    # Optional JSON override of the price table: {"model": {"input": usd_per_1m, "output": usd_per_1m}}
    llm_price_overrides: str | None = None

    # Trace limits (hard caps; requests are clamped to these)
    trace_max_depth: int = 5
    trace_default_depth: int = 3
    trace_max_window_hours: int = 720
    trace_default_window_hours: int = 72
    trace_max_nodes: int = 300
    trace_default_max_nodes: int = 150
    trace_hub_threshold: int = 25
    trace_per_account_cap: int = 40

    # Telemetry
    otel_exporter: str = "none"  # none | console | gcp
    log_level: str = "INFO"

    cors_origins: str = Field(default="http://localhost:5173")

    @property
    def fast_models(self) -> list[str]:
        return [m.strip() for m in self.gemini_fast_models.split(",") if m.strip()]

    @property
    def pro_models(self) -> list[str]:
        return [m.strip() for m in self.gemini_pro_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
