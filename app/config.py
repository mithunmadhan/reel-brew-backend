from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Creator Platform API"
    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/creator_platform"

    # Fernet key used to encrypt sensitive columns (e.g. SocialAccount.access_token).
    # Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str

    # Meta app credentials for the Instagram API with Instagram Login (Business/Creator
    # accounts) — from the app's "Instagram business login" API setup, not the general
    # Facebook Login app id/secret.
    meta_app_id: str
    meta_app_secret: str
    instagram_redirect_uri: str = "http://localhost:8000/auth/instagram/callback"

    gemini_api_key: str

    # Add secrets / API keys here as typed fields, e.g.:
    # openai_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
