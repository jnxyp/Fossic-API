"""One manager publishes complete, pre-encoded response snapshots."""
import datetime
import json
import math
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from pydantic import TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from config import CONFIG
from dao import ModDAO
from download_stats import DownloadStatsStore, checked_count, current_releases
from db import get_session_sync
from models import ModInfoTypes, GameInfo
from mod_recommendation import calculate_recommendation_score
import log

logger = log.get_logger(__name__)
MODS = TypeAdapter(list[ModInfoTypes])
GAMES = TypeAdapter(list[GameInfo])


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


@dataclass(frozen=True)
class Snapshot:
    responses: Mapping[str, bytes]
    count: int = 0
    last_updated: int = -1


def _fetch_with_retries(fetch, session, name):
    for attempt in range(1, 4):
        try:
            if session is not None:
                return fetch(session)
            with get_session_sync() as s:
                return fetch(s)
        except SQLAlchemyError:
            if attempt < 3:
                logger.warning('刷新 %s 失败 (第 %s/3 次)，5s 后重试', name, attempt)
                time.sleep(5)
            else:
                logger.exception('刷新 %s 失败，保留旧快照', name)
        except Exception:
            logger.exception('刷新 %s 失败，保留旧快照', name)
            return None
    return None


class SnapshotCache:
    def __init__(self, stats_store: DownloadStatsStore | None = None):
        self.stats_store = stats_store if stats_store is not None else DownloadStatsStore(
            CONFIG['download_stats']['db_path'])
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._snapshots = {
            'mods': Snapshot(MappingProxyType({
                'mods': b'[]', 'mods_all': b'[]', 'game_versions': b'[]',
                'mod_languages': b'{}', 'mod_categories': b'{}',
            })),
            'games': Snapshot(MappingProxyType({'games': b'[]'})),
        }

    def _fetch_mods(self, session: Session):
        dao = ModDAO(session)
        source_mods = MODS.validate_python(dao.get_all_mods())
        # Complete forum I/O before taking the statistics writer lock.
        metadata = {
            'game_versions': dao.get_game_versions(),
            'mod_languages': dao.get_mod_languages(),
            'mod_categories': dao.get_mod_categories(),
        }
        now = int(time.time())
        with self.stats_store.write_transaction() as connection:
            self.stats_store.apply_observations(connection, source_mods, now=now)
            summaries = self.stats_store.get_mod_summaries(
                connection, [mod.thread_meta.tid for mod in source_mods])
            mods = []
            for mod in source_mods:
                summary = summaries[mod.thread_meta.tid]
                releases = current_releases(mod.mod_releases).values()
                displayed = sum(r.download_count for r in releases
                    if type(r.download_count) is int and r.download_count >= 0)
                excluded = checked_count(summary['mod_download_count'] - displayed)
                # Validate the complete updated model: model_copy(update=...) skips validation.
                enriched = mod.__class__.model_validate({**mod.model_dump(), **summary,
                    'mod_excluded_download_count': excluded})
                score = calculate_recommendation_score(enriched, now=now)
                if not math.isfinite(score) or score < 0:
                    raise ValueError('Invalid Mod recommendation score')
                mods.append(enriched.model_copy(update={'mod_recommendation_score': score}))
            responses = {
                'mods_all': MODS.dump_json(mods, warnings='error'),
                'mods': MODS.dump_json([m for m in mods
                    if m.thread_meta.fid not in CONFIG['fossic']['modding_fids']], warnings='error'),
                **{key: _encode(value) for key, value in metadata.items()},
            }
            snapshot = Snapshot(MappingProxyType(responses), len(mods), now)
        # Commit precedes publication; any encoding/validation failure rolls back the ledger.
        return snapshot

    def _fetch_games(self, session: Session):
        from game_releases import GameDAO
        games = GameDAO(session).get_all_games()
        body = GAMES.dump_json(GAMES.validate_python(games), warnings='error')
        return Snapshot(MappingProxyType({'games': body}), len(games), int(time.time()))

    def refresh(self, session: Session | None = None) -> dict[str, bool]:
        result = {}
        with self._refresh_lock:
            for name, fetch in (('mods', self._fetch_mods), ('games', self._fetch_games)):
                snapshot = _fetch_with_retries(fetch, session, name)
                result[name] = snapshot is not None
                if snapshot is not None:
                    with self._lock:
                        self._snapshots[name] = snapshot
                    logger.info('SnapshotCache %s 刷新完成，共 %s 项', name, snapshot.count)
        return result

    def get_snapshot(self, name: str) -> Snapshot:
        with self._lock:
            return self._snapshots[name]

    def get_response(self, section: str, name: str) -> bytes:
        return self.get_snapshot(section).responses[name]

    def get_status(self) -> dict:
        now = int(time.time())
        interval = CONFIG['cache']['mod_cache_time']
        with self._lock:
            snapshots = dict(self._snapshots)
        parts = {}
        for name, snapshot in snapshots.items():
            updated = snapshot.last_updated
            parts[name] = {
                'status': 'ok' if updated >= 0 and now - updated <= interval * 2 else 'expired',
                'count': snapshot.count,
                'last_updated': updated,
                'last_updated_iso': datetime.datetime.fromtimestamp(updated, tz=datetime.timezone.utc).isoformat()
                    if updated >= 0 else None,
            }
        return {
            'status': 'ok' if all(p['status'] == 'ok' for p in parts.values()) else 'expired',
            'refresh_interval_seconds': interval,
            **parts,
        }


snapshot_cache = SnapshotCache()
