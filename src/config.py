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
    game_fids: set[int]


class CacheConfig(TypedDict):
    mod_cache_time: int


class AppConfig(TypedDict):
    db: DbConfig
    debug: bool
    fossic: FossicConfig
    cache: CacheConfig
    allowed_hosts: list[str]


CONFIG: AppConfig = {
    "allowed_hosts": [host.strip() for host in getenv(
        "ALLOWED_HOSTS", "api.fossic.org,localhost,127.0.0.1,[::1]"
    ).split(",") if host.strip()],
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
        "game_fids": {39},
    },
    "cache": {
        "mod_cache_time": int(getenv("MOD_CACHE_TIME", "300")),
    },
}
