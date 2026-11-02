import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://schools:schools@localhost:5432/schools"
    )
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    extract_model: str = os.getenv("EXTRACT_MODEL", "claude-haiku-5-5")
    translate_model: str = os.getenv("TRANSLATE_MODEL", "claude-haiku-5-5")
    agent_model: str = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
    embed_model: str = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    # Travel times
    google_maps_api_key: str | None = os.getenv("GOOGLE_MAPS_API_KEY")
    home_address: str | None = os.getenv("HOME_ADDRESS")
    timezone: str = os.getenv("TIMEZONE", "America/Los_Angeles")
    morning_lead_minutes: int = int(os.getenv("MORNING_LEAD_MINUTES", "30"))
    default_start_time: str = os.getenv("DEFAULT_START_TIME", "08:00")
    default_end_time: str = os.getenv("DEFAULT_END_TIME", "15:00")
    max_route_schools: int = int(os.getenv("MAX_ROUTE_SCHOOLS", "25"))
    user_agent: str = os.getenv(
        "CRAWL_USER_AGENT",
        "school-finder/0.1 (+https://github.com/agliga/private-school-finder)",
    )


settings = Settings()
