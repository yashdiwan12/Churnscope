from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = ""
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    cors_origins: str = "http://localhost:8501"
    # Optional trusted pin for the model artifact's SHA-256 (see app/ml/artifact.py).
    churn_model_sha256: str = ""

    # Authorization (Phase 5). An empty allow-list allows nobody; an empty key closes POST /events.
    allowed_emails: str = ""
    allowed_email_domains: str = ""
    ingest_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_email_list(self) -> set[str]:
        return _csv_lower(self.allowed_emails)

    @property
    def allowed_domain_list(self) -> set[str]:
        return _csv_lower(self.allowed_email_domains)


def _csv_lower(value: str) -> set[str]:
    return {p.strip().lower() for p in value.split(",") if p.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
