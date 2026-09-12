import json
import logging
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://syncguard:syncguard_local_demo@127.0.0.1:55432/syncguard?connect_timeout=5"
    )
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    simulator_url: str = "http://127.0.0.1:8100"


@lru_cache
def settings():
    return Settings()


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"level": record.levelname, **json.loads(record.getMessage())}, ensure_ascii=False)


logger = logging.getLogger("syncguard")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def event(name: str, **safe_fields):
    # Callers supply IDs, counts and statuses only, never payloads or exceptions.
    logger.info(json.dumps({"name": name, **safe_fields}))
