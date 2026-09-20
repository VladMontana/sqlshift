from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Настройки SQLShift Gateway"""

    host: str = "127.0.0.1"
    port: int = 8000
    api_prefix: str = "/v1"
    title: str = "SQLShift Gateway API"
    version: str = "0.1.0"

    pg_dsn: str | None = None
    ch_dsn: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


ServerSettings = Config
