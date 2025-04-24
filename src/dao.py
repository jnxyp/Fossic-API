from collections import defaultdict

from sqlmodel import Session, select, col

from config import CONFIG
from db import get_session_sync
import log
from models import ModInfoOriginal, ModInfoReposted, ModInfoTranslated, ModInfoType, ModInfoTypes, ThreadFeaturedLevel
from tables import ForumThread, ForumTypeOption, ForumTypeOptionVar
from utils import date_string_to_timestamp, get_thread_url

logger = log.setup_custom_logger(__name__)

FIDS = CONFIG["fossic"]["mod_fids"] | CONFIG["fossic"]["modding_fids"]

class BaseDAO:
    def __init__(self, session: Session):
        self.session = session


class ModDAO(BaseDAO):
    mod_info_identifier_mapping = {
        "modID": "mod_id",
        "modReleaseVersion": "mod_version",
        "modShortDes": "mod_short_description",
    }

    def get_game_versions(self) -> list[str]:
        game_versions = ForumTypeOption.get_game_versions(self.session)
        return list(game_versions.values())

    def get_mod_languages(self) -> list[str]:
        mod_languages = ForumTypeOption.get_mod_languages(self.session)
        return list(mod_languages.values())

    def get_mod_categories(self) -> list[str]:
        mod_types = ForumTypeOption.get_mod_types(self.session)
        return list(mod_types.values())

    def get_all_mods(self) -> list[ModInfoTypes]:
        # Fetch option values from the database
        game_versions = ForumTypeOption.get_game_versions(self.session)
        mod_languages = ForumTypeOption.get_mod_languages(self.session)
        mod_dependencies = ForumTypeOption.get_mod_dependencies(self.session)
        mod_types = ForumTypeOption.get_mod_types(self.session)
        mod_safe_rm = ForumTypeOption.get_mod_safe_rm(self.session)

        statement = (select(ForumTypeOption, ForumTypeOptionVar, ForumThread)
                     .join(ForumTypeOptionVar, col(ForumTypeOption.optionid) == col(ForumTypeOptionVar.optionid))
                     .where(col(ForumTypeOptionVar.sortid).in_([1, 2, 3]))
                     .join(ForumThread, col(ForumThread.tid) == col(ForumTypeOptionVar.tid))
                     .where(col(ForumThread.sortid) != 0)
                     .where(col(ForumThread.displayorder) >= 0)
                     .where(col(ForumThread.fid).in_(FIDS))
                     .order_by(col(ForumTypeOptionVar.tid).desc()))

        results = self.session.exec(statement).all()

        mod_info = defaultdict(dict)  # {tid: dict(ModInfo)}

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
                    "fid": thread.fid,
                    "featured_level": ThreadFeaturedLevel.from_digest(thread.digest),
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
            if "mod_info_type" not in mod_info[tid]:
                mod_info[tid]["mod_info_type"] = ModInfoType.from_sortid(
                    option_var.sortid)
            if "mod_publish_urls" not in mod_info[tid]:
                mod_info[tid]["mod_publish_urls"] = [get_thread_url(tid)]

            if identifier in self.mod_info_identifier_mapping:
                mod_info[tid][self.mod_info_identifier_mapping[identifier]] = value
                continue

            if identifier == "modName_cn":
                mod_info[tid]["mod_name_cn"] = value.strip().replace("\\", "")
                continue
            if identifier == "modName_en":
                mod_info[tid]["mod_name_en"] = value.strip().replace("\\", "")
                continue
            if identifier == "modAuthor":
                mod_info[tid].setdefault("mod_author_names", set())
                names = set()
                for name in value.split(","):
                    stripped_name = name.strip()
                    if stripped_name:
                        names.add(stripped_name)
                mod_info[tid]["mod_author_names"] |= names
                continue
            if identifier == "modTranslator":
                mod_info[tid].setdefault("mod_translator_names", set())
                names = set()
                for name in value.split(","):
                    stripped_name = name.strip()
                    if stripped_name:
                        names.add(stripped_name)
                mod_info[tid]["mod_translator_names"] |= names
                continue
            if identifier == "modDependency":
                mod_info[tid].setdefault("mod_dependency_names", set())
                mod_names = set()
                for id in value.split(" "):
                    if id in mod_dependencies:
                        name = mod_dependencies[id]
                        if name != "其它":
                            mod_names.add(name)
                mod_info[tid]["mod_dependency_names"] |= mod_names
                continue
            if identifier == "modDependencyNames":
                mod_info[tid].setdefault("mod_dependency_names", set())
                mod_names = set()
                for name in value.split("\n"):
                    stripped_name = name.strip()
                    if stripped_name and stripped_name not in {"无", "无依赖", "未知"}:
                        mod_names.add(stripped_name)
                mod_info[tid]["mod_dependency_names"] |= mod_names
                continue
            if identifier == "modConflict":
                mod_info[tid].setdefault("mod_conflict_names", set())
                mod_names = set()
                for name in value.split("\n"):
                    stripped_name = name.strip()
                    if stripped_name and stripped_name not in {"无", "无冲突", "未知"}:
                        mod_names.add(stripped_name)
                mod_info[tid]["mod_conflict_names"] |= mod_names
                continue
            if identifier == "modVersion":
                mod_info[tid].setdefault("mod_game_versions", set())
                versions = set()
                for version in value.split("\t"):
                    if version in game_versions:
                        versions.add(game_versions[version])
                mod_info[tid]["mod_game_versions"] |= versions
                continue
            if identifier == "modLanguage":
                # 如果没有值，默认是3（其它）
                mod_info[tid]["mod_language"] = mod_languages[value or "3"]
                continue
            if identifier == "modType":
                if value == "5":  # 如果是5（原内容类mod），则需要将其转换为2（内容类mod）
                    value = "2"
                mod_info[tid]["mod_category"] = mod_types[value]
                continue
            if identifier == "modVersion":
                mod_info[tid]["mod_game_version"] = game_versions[value]
                continue
            if identifier == "modSafeRm":
                mod_info[tid]["mod_safe_remove"] = mod_safe_rm[value] == "是"
                continue
            if identifier == "modPublishSite":
                mod_info[tid]["mod_publish_urls"].append(value)
                continue
            if identifier == "modUpdateDate":
                try:
                    mod_info[tid]["mod_update_date"] = date_string_to_timestamp(
                        value.replace("/", "-").replace(".", "-"))
                except ValueError:
                    logger.warning(f"帖子 {tid} 中包含无效的日期格式: {value}，将返回-1")
                    mod_info[tid]["mod_update_date"] = -1
                continue

        mod_info_objects = []
        for tid, info in mod_info.items():
            mod_info_type = info["mod_info_type"]
            if not "mod_id" in info or not info["mod_id"]:
                logger.warning(f"帖子 {tid} 中没有 mod_id，跳过该帖子")
                continue  # 跳过没有 mod_id 的老帖
            if mod_info_type == ModInfoType.ORIGINAL:
                mod_info_objects.append(ModInfoOriginal(**info))
            elif mod_info_type == ModInfoType.TRANSLATED:
                mod_info_objects.append(ModInfoTranslated(**info))
            elif mod_info_type == ModInfoType.REPOSTED:
                mod_info_objects.append(ModInfoReposted(**info))
            else:
                raise ValueError(f"Unknown mod info type: {mod_info_type}")

        def sort_key(mod): return (mod.mod_id, mod.thread_meta.tid)
        mod_info_objects.sort(key=sort_key)

        return mod_info_objects


if __name__ == "__main__":
    from db import get_session

    with get_session_sync() as session:
        dao = ModDAO(session)
        mods = dao.get_all_mods()
        for mod in mods:
            print(mod.model_dump_json())
