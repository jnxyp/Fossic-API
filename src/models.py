from enum import Enum
from typing import List, Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    title: str
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
    uploaded_at: int | None = None  # 附件 dateline，Unix 秒；未知为 null
    download_url: str | None = None  # 稳定论坛入口，不含签名或存储地址


class ModAiDeclaration(BaseModel):
    """Normalized publisher declaration, not an automated assessment."""
    model_config = ConfigDict(extra='forbid')

    status: Literal['undeclared', 'yes', 'no']
    code: Literal['undeclared', 'none', 'assisted', 'full']
    art: Literal['undeclared', 'none', 'assisted', 'full']
    audio: Literal['undeclared', 'none', 'assisted', 'full']
    text: Literal['undeclared', 'none', 'assisted', 'full']

    @model_validator(mode='after')
    def validate_dimensions(self) -> Self:
        dimensions = (self.code, self.art, self.audio, self.text)
        if self.status == 'undeclared':
            valid = all(value == 'undeclared' for value in dimensions)
        elif self.status == 'no':
            valid = all(value == 'none' for value in dimensions)
        else:
            valid = ('undeclared' not in dimensions
                     and any(value != 'none' for value in dimensions))
        if not valid:
            raise ValueError('AI declaration status and dimensions are inconsistent')
        return self

    @classmethod
    def undeclared(cls) -> Self:
        return cls(status='undeclared', code='undeclared', art='undeclared',
                   audio='undeclared', text='undeclared')


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
    mod_ai_declaration: ModAiDeclaration = Field(
        default_factory=ModAiDeclaration.undeclared,
        description='发布者自愿填写的生成式AI声明，不代表质量评价或平台检测；'
                    '未声明时status及四个维度均为undeclared',
    )
    mod_download_count: int = Field(default=0, ge=0, strict=True,
        description='本发布帖跨版本、按附件去重的持久累计下载量，含已删除或排除附件的冻结贡献')
    mod_excluded_download_count: int = Field(default=0, ge=0, strict=True,
        description='未被当前 releases 有效计数覆盖的历史下载贡献，含已删除/排除附件及源计数回退差额；'
                    '与当前附件有效计数去重之和相加等于 mod_download_count')
    mod_recommendation_score: float = Field(
        default=0.0, ge=0, allow_inf_nan=False,
        description='持久累计下载总量的综合推荐分；新鲜度初始5分、15天线性衰减，随Mod快照刷新',
    )
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



class GameRelease(SQLModel):
    attachment_id: int
    is_full_game: bool
    game_version: str
    platform: Literal['windows', 'macos', 'linux', 'universal']
    language: Literal['zh-Hans', 'zh-Hant', 'en', 'other']
    package_type: Literal['zip', 'self_extracting', 'other']
    release_version: str
    display_name: str | None = None
    download_count: int | None = None
    file_name: str | None = None
    file_size: int | None = None
    uploaded_at: int | None = None
    download_url: str | None = None


class GameInfo(SQLModel):
    game_release_name: str | None = None
    game_release_version: str | None = None
    game_author_names: list[str] = []
    game_allow_direct_download: bool = False
    game_publish_urls: list[str]
    game_releases: list[GameRelease] | None = None
    thread_meta: ThreadMeta
