from typing import List
from fastapi import APIRouter
from fastapi_cache.decorator import cache

from cache import mod_cache
from models import ModInfoTypes

router = APIRouter()

@router.get("/mods", response_model=List[ModInfoTypes])
@cache(expire=600)
async def get_all_mods(include_modding:bool=False) -> List[ModInfoTypes]:
    if not include_modding:
        return mod_cache.get_all_mods_no_modding()
    return mod_cache.get_all_mods()