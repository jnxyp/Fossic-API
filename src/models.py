from enum import Enum
from typing import List
from sqlmodel import SQLModel


class ModInfoType(Enum):
    ORIGINAL = 'original'
    TRANSLATED = 'translated'
    REPOSTED = 'reposted'
    
    @classmethod
    def from_sortid(cls, sortid: int) -> 'ModInfoType':
        if sortid == 1:
            return cls.ORIGINAL
        elif sortid == 3:
            return cls.TRANSLATED
        elif sortid == 2:
            return cls.REPOSTED
        else:
            raise ValueError(f"Invalid sortid: {sortid}")

class ThreadFeaturedLevel(Enum):
    NOT_FEATURED = 0
    FEATURED_1 = 1
    FEATURED_2 = 2
    FEATURED_3 = 3

    @classmethod
    def from_digest(cls, digest: int) -> 'ThreadFeaturedLevel':
        if digest == 0:
            return cls.NOT_FEATURED
        elif digest in (1, 2, 3):
            return cls(digest)
        else:
            raise ValueError(f"Invalid digest value: {digest}")

class ThreadMeta(SQLModel):
    tid: int
    uid: int
    featured: ThreadFeaturedLevel
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
    mod_safe_remove: bool
    mod_dependencies: List[str] = []
    mod_conflicts: List[str] = []
    mod_short_description: str
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

ModInfoTypes = ModInfoOriginal | ModInfoTranslated | ModInfoReposted

class ModIndex(SQLModel):
    mods: List[ModInfoTypes] = []
