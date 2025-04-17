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
}