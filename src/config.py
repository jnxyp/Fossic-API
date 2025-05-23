from os import getenv
from dotenv import load_dotenv
load_dotenv()

CONFIG = {
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
        "mod_fids": {46,60,78},
        "modding_fids": {71},
    },
    "cache": {
        "api_cache_time": int(getenv("API_CACHE_TIME", "300")),
        "mod_cache_time": int(getenv("MOD_CACHE_TIME", "300")),
    },
}