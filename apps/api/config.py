from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "development-only-secret-change-me-32"
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
