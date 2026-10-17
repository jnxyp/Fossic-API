from fastapi import APIRouter
from fastapi.responses import Response

from cache import snapshot_cache
from models import ModInfoTypes, GameInfo

router = APIRouter()


def cached_response(section: str, name: str) -> Response:
    return Response(content=snapshot_cache.get_response(section, name), media_type='application/json')


@router.get("/mods", response_model=list[ModInfoTypes])
async def get_all_mods(include_modding: bool = False) -> Response:
    return cached_response('mods', 'mods_all' if include_modding else 'mods')


@router.get("/meta/game_versions", response_model=list[str])
async def get_game_versions() -> Response:
    return cached_response('mods', 'game_versions')


@router.get("/meta/mod_languages", response_model=dict[str, str])
async def get_mod_languages() -> Response:
    return cached_response('mods', 'mod_languages')


@router.get("/meta/mod_categories", response_model=dict[str, str])
async def get_mod_categories() -> Response:
    return cached_response('mods', 'mod_categories')


@router.get('/games', response_model=list[GameInfo])
async def get_all_games() -> Response:
    return cached_response('games', 'games')
