from enum import Enum
from typing import List, Literal
from sqlmodel import SQLModel


class ModInfoType(str, Enum):
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
    fid: int # 版块ID
    featured_level: ThreadFeaturedLevel
    recommend_weight: int  # 推荐数
    heats: int  # 累计参与热度，不含时间衰减
    views: int  # 论坛已落库的累计浏览量


class AdminNotes(SQLModel):
    mod_index_comment: str | None = None
    thread_comment: str | None = None  # db field name: adminThreadComment

class ModRelease(SQLModel):
    attachment_id: int
    game_version_id: str
    game_version: str
    mod_version: str
    display_name: str | None = None
    download_count: int | None = None  # 无有效的本帖附件记录时为 null
    file_name: str | None = None
    file_size: int | None = None
    download_url: str | None = None  # 稳定论坛入口，不含签名或存储地址


class ModInfo(SQLModel):
    mod_info_type: ModInfoType
    mod_id: str
    mod_name_cn: str
    mod_author_names: List[str] = []
    mod_category: str
    mod_game_versions: List[str] = []
    mod_version: str  # db field name: modReleaseVersion
    mod_releases: list[ModRelease] | None = None
    mod_allow_direct_download: bool = False
    mod_safe_remove: bool
    mod_dependency_names: List[str] = []
    mod_conflict_names: List[str] = []
    mod_short_description: str
    mod_language: str
    mod_update_date: int
    mod_publish_urls: List[str]

    admin_notes: AdminNotes
    thread_meta: ThreadMeta

class ModInfoOriginal(ModInfo):
    mod_info_type: Literal[ModInfoType.ORIGINAL] = ModInfoType.ORIGINAL
    mod_name_en: str | None = None


class ModInfoTranslated(ModInfo):
    mod_info_type: Literal[ModInfoType.TRANSLATED] = ModInfoType.TRANSLATED
    mod_name_en: str
    mod_translator_names: List[str] = []


class ModInfoReposted(ModInfo):
    mod_info_type: Literal[ModInfoType.REPOSTED] = ModInfoType.REPOSTED
    mod_name_en: str

ModInfoTypes = ModInfoOriginal | ModInfoTranslated | ModInfoReposted

