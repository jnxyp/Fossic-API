from fastapi import APIRouter, Depends
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from sqlmodel import Session

from dao import ModIndexDAO
from db import get_session, get_session_sync
from models import ModIndex

router = APIRouter()

@router.get("/mod_index", response_model=ModIndex)
@cache(expire=600)
async def get_mod_index() -> ModIndex:
    mod_index_dao = ModIndexDAO(get_session_sync())
    return ModIndex(mods=mod_index_dao.get_all_mods())