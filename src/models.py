from enum import Enum
from typing import List
from sqlmodel import SQLModel


class ModInfoType(Enum):
    ORIGINAL = 1
    TRANSLATED = 3
    REPOSTED = 2


class ThreadMeta(SQLModel):
    tid: int
    uid: int
    featured: int  # 是否精华帖 0 否 1-3 精华1-3
    recommend_weight: int  # 推荐数


class AdminNotes(SQLModel):
    mod_index_comment: str | None = None
    thread_comment: str | None = None  # db field name: adminThreadComment


class ModInfo(SQLModel):
    mod_info_type: ModInfoType
    mod_id: str
    mod_name_cn: str
    mod_author: str
    mod_category: str  # todo: Enum from DB
    mod_game_version: str  # todo: Enum from DB, db field name: modVersion
    mod_version: str  # db field name: modReleaseVersion
    mod_safe_rm: bool
    mod_dependencies: List[str] = []
    mod_conflicts: List[str] = []
    mod_short_desc: str
    mod_language: str  # todo: Enum from DB
    mod_update_date: str  # todo: DateTime from DB

    admin_notes: AdminNotes | None = None
    thread_meta: ThreadMeta | None = None


class ModInfoOriginal(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.ORIGINAL
    mod_name_en: str | None = None


class ModInfoTranslated(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.TRANSLATED
    mod_name_en: str
    mod_publish_url: str  # db field name: modPublishSite
    mod_translator: str


class ModInfoReposted(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.REPOSTED
    mod_name_en: str
    mod_publish_url: str  # db field name: modPublishSite
