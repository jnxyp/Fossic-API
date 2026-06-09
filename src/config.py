from os import getenv
from typing import TypedDict
from dotenv import load_dotenv
load_dotenv()


class DbConfig(TypedDict):
    host: str | None
    port: str | None
    user: str | None
    password: str | None
    db: str | None


class FossicConfig(TypedDict):
    url: str
    api_url: str
    mod_fids: set[int]
    modding_fids: set[int]


class CacheConfig(TypedDict):
    api_cache_time: int
    mod_cache_time: int


class AppConfig(TypedDict):
    db: DbConfig
    debug: bool
    fossic: FossicConfig
    cache: CacheConfig


CONFIG: AppConfig = {
    "db": {
        "host": getenv("DB_HOST"),
        "port": getenv("DB_PORT"),
        "user": getenv("DB_USER"),
        "password": getenv("DB_PASSWORD"),
        "db": getenv("DB_DATABASE"),
    },
    "debug": getenv("DEBUG", "false").lower() == "true",
    "fossic": {
        "url": "https://www.fossic.org",
        "api_url": "https://api.fossic.org",
        "mod_fids": {46, 60, 78},
        "modding_fids": {71},
    },
    "cache": {
        "api_cache_time": int(getenv("API_CACHE_TIME", "300")),
        "mod_cache_time": int(getenv("MOD_CACHE_TIME", "300")),
    },
}
