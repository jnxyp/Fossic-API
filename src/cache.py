import threading
import time
from typing import TypedDict
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from config import CONFIG
from dao import ModDAO
from db import get_session_sync
import log
from models import ModInfoTypes


class _FetchResult(TypedDict):
    game_versions: list[str]
    mod_languages: dict[str, str]
    mod_categories: dict[str, str]
    mod_dependencies: dict[str, str]
    mods: list[ModInfoTypes]

logger = log.get_logger(__name__)


def _fetch_with_retries(fetch, session, name):
    for attempt in range(1, 4):
        try:
            if session is not None:
                return fetch(session)
            with get_session_sync() as s:
                return fetch(s)
        except SQLAlchemyError:
            if attempt < 3:
                logger.warning('刷新 %s 失败 (第 %s/3 次)，5s 后重试', name, attempt)
                time.sleep(5)
            else:
                logger.exception('刷新 %s 失败，保留旧快照', name)
        except Exception:
            logger.exception('刷新 %s 失败，保留旧快照', name)
            return None
    return None

modding_fids = CONFIG["fossic"]["modding_fids"]

class ModCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._mods: list[ModInfoTypes] = []
        self._game_versions: list[str] = []
        self._mod_languages: dict[str,str] = {}
        self._mod_categories: dict[str,str] = {}
        self._mod_dependencies: dict[str,str] = {}
        self._last_updated = -1

    def _fetch(self, session: Session) -> _FetchResult:
        mod_dao = ModDAO(session)
        return {
            "game_versions": mod_dao.get_game_versions(),
            "mod_languages": mod_dao.get_mod_languages(),
            "mod_categories": mod_dao.get_mod_categories(),
            "mod_dependencies": mod_dao.get_mod_dependencies(),
            "mods": mod_dao.get_all_mods(),
        }

    def refresh(self, session: Session | None = None) -> bool:
        logger.info("开始刷新 ModCache")
        data = _fetch_with_retries(self._fetch, session, 'ModCache')
        if data is None:
            return False

        with self._lock:
            self._game_versions = data["game_versions"]
            self._mod_languages = data["mod_languages"]
            self._mod_categories = data["mod_categories"]
            self._mod_dependencies = data["mod_dependencies"]
            self._mods = data["mods"]
            self._last_updated = int(time.time())

        logger.info(f"ModCache 刷新完成, 共 {len(self._mods)} 个有效 mod")
        return True

    def get_all_mods(self) -> list[ModInfoTypes]:
        with self._lock:
            return self._mods

    def get_all_mods_no_modding(self) -> list[ModInfoTypes]:
        with self._lock:
            return [mod for mod in self._mods if mod.thread_meta.fid not in modding_fids]

    def get_update_time(self) -> int:
        with self._lock:
            return self._last_updated

    def get_game_versions(self) -> list[str]:
        with self._lock:
            return self._game_versions

    def get_mod_languages(self) -> dict[str,str]:
        with self._lock:
            return self._mod_languages

    def get_mod_categories(self) -> dict[str,str]:
        with self._lock:
            return self._mod_categories

mod_cache = ModCache()


class GameCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._games = []
        self._last_updated = -1

    def _fetch(self, session):
        from game_releases import GameDAO
        return GameDAO(session).get_all_games()

    def refresh(self, session: Session | None = None) -> bool:
        games = _fetch_with_retries(self._fetch, session, 'GameCache')
        if games is None:
            return False
        with self._lock:
            self._games = games
            self._last_updated = int(time.time())
        logger.info('GameCache 刷新完成，共 %s 个游戏发布帖', len(games))
        return True

    def get_all_games(self):
        with self._lock:
            return self._games

    def get_update_time(self):
        with self._lock:
            return self._last_updated


game_cache = GameCache()
