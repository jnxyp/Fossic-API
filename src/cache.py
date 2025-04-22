from typing import List

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
        self._mods: List[ModInfoTypes] = []
        
    def refresh(self, session:Session | None = None):
        logger.info("开始刷新 ModCache")
        mod_dao = ModDAO(session or get_session_sync())
        self._mods = mod_dao.get_all_mods()
        logger.info("ModCache 刷新完成")
        
    def get_all_mods(self) -> List[ModInfoTypes]:
        return self._mods
    
    def get_all_mods_no_modding(self) -> List[ModInfoTypes]:
        return [mod for mod in self._mods if mod.thread_meta.fid not in modding_fids]
    
    
mod_cache = ModCache()
mod_cache.refresh()