from collections import defaultdict
from typing import List

from sqlmodel import Session, select, col

from db import get_session_sync
from models import ThreadFeaturedLevel
from tables import ForumThread, ForumTypeOption, ForumTypeOptionVar


class BaseDAO:
    def __init__(self, session: Session):
        self.session = session


class ModIndexDAO(BaseDAO):
    ModInfoIdentifierMapping = {
        "modID": "mod_id",
        "modName_cn": "mod_name_cn",
        "modName_en": "mod_name_en",
        "modAuthor": "mod_author",
        "modTranslator": "mod_translator",
        "modVersion": "mod_game_version",
        "modReleaseVersion": "mod_version",
        "modUpdateDate": "mod_update_date",
        "modSafeRm": "mod_safe_remove",
        "modPublishSite": "mod_publish_url",
        "modShortDes": "mod_short_description",
    }
    
    def get_all_mods(self):
        statement = select(ForumTypeOption, ForumTypeOptionVar, ForumThread)\
            .join(ForumTypeOptionVar, col(ForumTypeOption.optionid) == col(ForumTypeOptionVar.optionid))\
            .where(col(ForumTypeOptionVar.sortid).in_([1,2,3]))\
            .join(ForumThread, col(ForumThread.tid) == col(ForumTypeOptionVar.tid))\
            .limit(100)\
            .order_by(col(ForumTypeOptionVar.tid).desc())



        results = self.session.exec(statement).all()
        
        mod_info = defaultdict(dict) # {tid: dict(ModInfo)}
        
        for option, option_var, thread in results:
            title = option.title
            identifier = option.identifier
            value = option_var.value
            tid = option_var.tid

            # Parse ThreadMeta
            if "thread_meta" not in mod_info[tid]:
                mod_info[tid]["thread_meta"] = {
                    "tid": tid,
                    "uid": thread.authorid,
                    "featured": ThreadFeaturedLevel.from_digest(thread.digest),
                    "recommend_weight": thread.recommends,
                }

            # Parse AdminNotes
            if "admin_notes" not in mod_info[tid]:
                mod_info[tid]["admin_notes"] = {}
            if identifier == "modIndexComment":
                mod_info[tid]["admin_notes"]["mod_index_comment"] = value
                continue
            if identifier == "adminThreadComment":
                mod_info[tid]["admin_notes"]["thread_comment"] = value
                continue
            
            # Parse ModInfo
            if identifier in self.ModInfoIdentifierMapping:
                mod_info[tid][self.ModInfoIdentifierMapping[identifier]] = value

if __name__ == "__main__":
    from db import get_session

    with get_session_sync() as session:
        dao = ModIndexDAO(session)
        mods = dao.get_all_mods()
        for mod in mods:
            name = mod[0].title
            value = mod[1].value
            print(mod)
