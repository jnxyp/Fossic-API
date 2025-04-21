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
    mod_author_names: List[str]
    mod_category: str
    mod_game_versions: List[str]
    mod_version: str  # db field name: modReleaseVersion
    mod_safe_remove: bool
    mod_dependency_names: List[str] = []
    mod_conflict_names: List[str] = []
    mod_short_description: str
    mod_language: str
    mod_update_date: int
    mod_publish_urls: List[str]

    admin_notes: AdminNotes | None = None
    thread_meta: ThreadMeta | None = None

class ModInfoOriginal(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.ORIGINAL
    mod_name_en: str | None = None


class ModInfoTranslated(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.TRANSLATED
    mod_name_en: str
    mod_translator_names: List[str]


class ModInfoReposted(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.REPOSTED
    mod_name_en: str

ModInfoTypes = ModInfoOriginal | ModInfoTranslated | ModInfoReposted

class ModIndex(SQLModel):
    mods: List[ModInfoTypes] = []
