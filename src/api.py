import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session
from db import get_session
from ratings import read_ratings, RatingUnavailable, RatingSummary
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


# Synchronous routes run DB work off the event loop. Bounded bulk avoids N+1 reads.
# No shared HTTP cache: changes to guest permissions take effect on the next request.
def rating_response(session: Session, tids: list[int]) -> dict:
    try:
        return read_ratings(session, tids)
    except (SQLAlchemyError, RatingUnavailable):
        raise HTTPException(status_code=503, detail='Ratings temporarily unavailable',
                            headers={'Cache-Control': 'no-store'}) from None


@router.get('/mods/ratings', response_model=dict[int, RatingSummary])
def get_mod_ratings(tid: list[int] = Query(min_length=1, max_length=100),
                    session: Session = Depends(get_session)) -> Response:
    if any(value < 1 or value > 4294967295 for value in tid):
        raise HTTPException(status_code=422, detail='Invalid thread ID')
    return Response(content=json.dumps(rating_response(session, tid)), media_type='application/json',
                    headers={'Cache-Control': 'no-store'})


@router.get('/mods/{tid}/rating', response_model=RatingSummary)
def get_mod_rating(tid: int, session: Session = Depends(get_session)) -> Response:
    if tid < 1 or tid > 4294967295:
        raise HTTPException(status_code=422, detail='Invalid thread ID')
    data = rating_response(session, [tid]).get(tid)
    if data is None:
        raise HTTPException(status_code=404, detail='Mod not found', headers={'Cache-Control': 'no-store'})
    return Response(content=json.dumps(data), media_type='application/json', headers={'Cache-Control': 'no-store'})
