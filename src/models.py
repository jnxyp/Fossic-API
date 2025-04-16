from enum import Enum
from typing import List
from sqlmodel import SQLModel


class ModInfoType(Enum):
    ORIGINAL = 1
    TRANSLATED = 3
    REPOSTED = 2


class ModInfo(SQLModel):
    mod_info_type: ModInfoType
    mod_id: str
    mod_name_cn: str
    mod_author: str
    mod_category: str  # todo: Enum from DB
    mod_version: str
    mod_safe_rm: bool
    mod_dependencies: List[str] = []
    mod_conflicts: List[str] = []
    mod_short_desc: str
    mod_language: str  # todo: Enum from DB
    mod_update_date: str  # todo: DateTime from DB


class ModInfoOriginal(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.ORIGINAL
    mod_name_en: str | None = None


class ModInfoTranslated(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.TRANSLATED
    mod_name_en: str
    mod_publish_site: str
    mod_translator: str


class ModInfoReposted(ModInfo):
    mod_info_type: ModInfoType = ModInfoType.REPOSTED
    mod_name_en: str
    mod_publish_site: str
