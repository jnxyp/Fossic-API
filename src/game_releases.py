"""Read game release metadata using the forum's saved schema."""
import re
from sqlmodel import select, col
from dao import BaseDAO
from models import GameRelease, GameInfo, ThreadMeta, ThreadFeaturedLevel
from mod_releases import decode_discuz_json
from tables import ForumThread, ForumTypeOption, ForumTypeOptionVar
from attachments import populate_attachment_metadata
from config import CONFIG
from utils import get_thread_url
import log

logger = log.get_logger(__name__)

# Starsector 0.98a-RC8 in-game credits (title/A/oOOO.class).
# Main creators only; special thanks and localization credits are separate.
STARSECTOR_AUTHOR_NAMES = (
    'Alex Mosolov', 'David Baumgart', 'Ivaylo Kovatchev', 'Stian Stark',
)


def parse_game_releases(value: str | None, tid: int) -> list[GameRelease] | None:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        entries = decode_discuz_json(value)
        if not isinstance(entries, list) or len(entries) > 200:
            raise ValueError('expected up to 200 release entries')
    except (TypeError, ValueError, RecursionError):
        logger.warning('帖子 %s gameReleaseInfoMapping 无法解析为发布数组', tid)
        return None
    releases, seen, rejected = [], set(), 0
    for entry in entries:
        try:
            if not isinstance(entry, dict) or set(entry) - {
                    'aid', 'isFullGame', 'gameVersion', 'platform', 'language',
                    'packageType', 'releaseVersion', 'displayName'}:
                raise ValueError('invalid entry keys')
            aid = entry.get('aid')
            if isinstance(aid, str) and re.fullmatch(r'[0-9]+', aid):
                aid = int(aid)
            if type(aid) is not int or not 0 < aid <= 4294967295 or aid in seen:
                raise ValueError('invalid or duplicate attachment ID')
            if type(entry.get('isFullGame')) is not bool:
                raise ValueError('expected a boolean')
            version, release_version = entry.get('gameVersion'), entry.get('releaseVersion')
            for value, limit in ((version, 64), (release_version, 128)):
                if not isinstance(value, str) or not value.strip() or len(value) > limit:
                    raise ValueError('invalid version')
            display = entry.get('displayName')
            if display is not None and (not isinstance(display, str) or len(display) > 200):
                raise ValueError('invalid display name')
            release = GameRelease(attachment_id=aid, is_full_game=entry['isFullGame'],
                game_version=version.strip(), release_version=release_version.strip(),
                platform=entry.get('platform'), language=entry.get('language'),
                package_type=entry.get('packageType'),
                display_name=(display.strip() or None) if display else None)
            release.model_dump_json().encode('utf-8')
            releases.append(release)
            seen.add(aid)
        except (TypeError, ValueError, UnicodeError):
            rejected += 1
    if rejected:
        logger.warning('帖子 %s gameReleaseInfoMapping 已过滤 %s/%s 个无效条目', tid, rejected, len(entries))
    return releases


class GameDAO(BaseDAO):
    def get_all_games(self) -> list[GameInfo]:
        statement = (select(ForumThread, ForumTypeOption, ForumTypeOptionVar)
            .join(ForumTypeOptionVar, col(ForumTypeOptionVar.tid) == col(ForumThread.tid))
            .join(ForumTypeOption, col(ForumTypeOption.optionid) == col(ForumTypeOptionVar.optionid))
            .where(col(ForumThread.sortid) == 9)
            .where(col(ForumTypeOptionVar.sortid) == col(ForumThread.sortid))
            .where(col(ForumTypeOptionVar.fid) == col(ForumThread.fid))
            .where(col(ForumThread.displayorder) >= 0)
            .where(col(ForumThread.fid).in_(CONFIG['fossic']['game_fids']))
            .where(col(ForumTypeOption.identifier).in_([
                'gameReleaseInfoMapping', 'gameAllowDirectDownload', 'gameReleaseAuthor',
                'gameReleaseName', 'gameReleaseVersion']))
            .order_by(col(ForumThread.tid).desc()))
        games = {}
        for thread, option, value in self.session.exec(statement).all():
            if thread.tid not in games:
                games[thread.tid] = GameInfo(game_author_names=list(STARSECTOR_AUTHOR_NAMES),
                    game_publish_urls=[get_thread_url(thread.tid)],
                    thread_meta=ThreadMeta(title=thread.subject, tid=thread.tid, uid=thread.authorid, fid=thread.fid,
                        featured_level=ThreadFeaturedLevel.from_digest(thread.digest),
                        recommend_weight=thread.recommends, heats=thread.heats, views=thread.views))
            game = games[thread.tid]
            if option.identifier == 'gameReleaseInfoMapping':
                game.game_releases = parse_game_releases(value.value, thread.tid)
            elif option.identifier == 'gameReleaseAuthor':
                game.game_author_names = sorted(set(STARSECTOR_AUTHOR_NAMES) |
                    {name.strip() for name in value.value.split(',') if name.strip()})
            elif option.identifier == 'gameReleaseName':
                game.game_release_name = value.value.strip() or None
            elif option.identifier == 'gameReleaseVersion':
                game.game_release_version = value.value.strip() or None
            elif option.identifier == 'gameAllowDirectDownload':
                try:
                    choices = ForumTypeOption.extract_choices_from_rules(option.rules)
                    game.game_allow_direct_download = choices.get(value.value) == '是'
                except (ValueError, TypeError, KeyError, AttributeError):
                    logger.warning('帖子 %s gameAllowDirectDownload 选项无效，默认关闭', thread.tid)
        result = list(games.values())
        populate_attachment_metadata(self.session,
            ((game.thread_meta.tid, game.game_releases or [], game.game_allow_direct_download) for game in result),
            'gamedownload')
        return result
