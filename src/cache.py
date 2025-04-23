import time
from sqlmodel import Session

from config import CONFIG
from dao import ModDAO
from db import get_session_sync
import log
from models import ModInfoTypes

logger = log.setup_custom_logger(__name__)

modding_fids = CONFIG["fossic"]["modding_fids"]

class ModCache:
    def __init__(self):
        self._mods: list[ModInfoTypes] = []
        
    def refresh(self, session:Session | None = None) -> bool:
        logger.info("开始刷新 ModCache")
        try:
            mod_dao = ModDAO(session or get_session_sync())
            self._mods = mod_dao.get_all_mods()
        except Exception as e:
            logger.error(f"刷新 ModCache 失败: {e}")
            return False
        logger.info(f"ModCache 刷新完成, 共 {len(self._mods)} 个有效 mod")
        return True
        
    def get_all_mods(self) -> list[ModInfoTypes]:
        return self._mods
    
    def get_all_mods_no_modding(self) -> list[ModInfoTypes]:
        return [mod for mod in self._mods if mod.thread_meta.fid not in modding_fids]

mod_cache = ModCache()