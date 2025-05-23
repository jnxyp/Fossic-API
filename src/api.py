from fastapi import APIRouter
from fastapi_cache.decorator import cache

from cache import mod_cache
from config import CONFIG
from models import ModInfoTypes

router = APIRouter()

@router.get("/mods", response_model=list[ModInfoTypes])
@cache(expire=CONFIG["cache"]["api_cache_time"])
async def get_all_mods(include_modding:bool=False) -> list[ModInfoTypes]:
    if not include_modding:
        return mod_cache.get_all_mods_no_modding()
    return mod_cache.get_all_mods()

@router.get("/meta/game_versions", response_model=list[str])
@cache(expire=CONFIG["cache"]["api_cache_time"])
async def get_game_versions() -> list[str]:
    return mod_cache.get_game_versions()

@router.get("/meta/mod_languages", response_model=dict[str, str])
@cache(expire=CONFIG["cache"]["api_cache_time"])
async def get_mod_languages() -> dict[str, str]:
    return mod_cache.get_mod_languages()

@router.get("/meta/mod_categories", response_model=dict[str, str])
@cache(expire=CONFIG["cache"]["api_cache_time"])
async def get_mod_categories() -> dict[str, str]:
    return mod_cache.get_mod_categories()