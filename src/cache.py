import threading
import time
from sqlmodel import Session

from config import CONFIG
from dao import ModDAO
from db import get_session_sync
import log
from models import ModInfoTypes

logger = log.get_logger(__name__)

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

    def _fetch(self, session: Session) -> dict:
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
        try:
            if session:
                data = self._fetch(session)
            else:
                with get_session_sync() as s:
                    data = self._fetch(s)
        except Exception as e:
            logger.error(f"刷新 ModCache 失败: {e}", exc_info=True)
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
