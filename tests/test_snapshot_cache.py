import json
import math

import pytest
import threading
from types import MappingProxyType

from fastapi.testclient import TestClient
from sqlalchemy import event

import api
import cache
import main
from cache import SnapshotCache, Snapshot
from download_stats import DownloadStatsStore
from tables import ForumAttachment, ForumTypeOptionVar
from test_mods_integration import session


def test_requests_use_encoded_snapshot_without_sql_or_encoding(session, monkeypatch):
    manager = SnapshotCache()
    monkeypatch.setattr(api, 'snapshot_cache', manager)
    monkeypatch.setattr(main, 'snapshot_cache', manager)
    monkeypatch.setattr(main, 'refresh_cache', lambda: manager.refresh(session))
    with TestClient(main.app) as client:
        paths = ['/mods', '/mods?include_modding=true', '/games',
                 '/meta/game_versions', '/meta/mod_languages', '/meta/mod_categories']
        expected = [client.get(path).content for path in paths]
        for body in expected[:2]:
            mods = json.loads(body)
            assert mods
            assert all('mod_download_counts_by_game_version' not in mod for mod in mods)
        def reject(*args, **kwargs):
            raise AssertionError('request must not query or encode')
        event.listen(session.bind, 'before_cursor_execute', reject)
        try:
            monkeypatch.setattr(manager.stats_store, '_connect', reject)
            monkeypatch.setattr(cache, 'calculate_recommendation_score', reject)
            monkeypatch.setattr(cache, '_encode', reject)
            monkeypatch.setattr(cache.TypeAdapter, 'dump_json', reject)
            for path, body in zip(paths, expected):
                response = client.get(path)
                assert response.status_code == 200 and response.content == body
                assert response.headers['content-type'] == 'application/json'
                assert 'x-fastapi-cache' not in response.headers
            assert client.get('/mods?include_modding=false').content == expected[0]
            status = client.get('/status').json()
            assert set(status) == {'status', 'docs_url', 'cache'}
            assert status['cache']['mods']['count'] == 4
            assert status['cache']['games']['count'] == 0
            assert status['cache']['status'] == 'ok'
        finally:
            event.remove(session.bind, 'before_cursor_execute', reject)


def test_encoding_failure_keeps_entire_section(session, monkeypatch):
    manager = SnapshotCache()
    manager.refresh(session)
    previous = manager.get_snapshot('mods')
    def broken(_):
        raise ValueError('cannot encode metadata')
    monkeypatch.setattr(cache, '_encode', broken)
    assert manager.refresh(session) == {'mods': False, 'games': True}
    assert manager.get_snapshot('mods') is previous


def test_status_uninitialized_and_partial_expiry(session, monkeypatch):
    manager = SnapshotCache()
    status = manager.get_status()
    assert status['status'] == 'expired'
    assert status['mods']['last_updated_iso'] is None
    monkeypatch.setattr(cache.time, 'time', lambda: 1000)
    assert all(manager.refresh(session).values())
    interval = status['refresh_interval_seconds']
    monkeypatch.setattr(cache.time, 'time', lambda: 1000 + 2 * interval)
    assert manager.get_status()['status'] == 'ok'
    monkeypatch.setattr(cache.time, 'time', lambda: 1001 + 2 * interval)
    def broken(_):
        raise ValueError('game unavailable')
    monkeypatch.setattr(manager, '_fetch_games', broken)
    assert manager.refresh(session) == {'mods': True, 'games': False}
    status = manager.get_status()
    assert status['status'] == 'expired'
    assert status['mods']['status'] == 'ok' and status['games']['status'] == 'expired'
    assert status['games']['last_updated'] == 1000


def test_publish_only_after_all_responses_are_ready(monkeypatch):
    manager = SnapshotCache()
    old = manager.get_snapshot('mods')
    started, release = threading.Event(), threading.Event()
    def fetch(_):
        started.set()
        assert release.wait(5)
        return Snapshot(MappingProxyType({'mods': b'[1]', 'mods_all': b'[1,2]'}), 2, 1000)
    monkeypatch.setattr(manager, '_fetch_mods', fetch)
    monkeypatch.setattr(manager, '_fetch_games', lambda _: manager.get_snapshot('games'))
    worker = threading.Thread(target=lambda: manager.refresh(object()))
    worker.start()
    try:
        assert started.wait(5)
        assert manager.get_snapshot('mods') is old
        assert manager.get_response('mods', 'mods') == b'[]'
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    snapshot = manager.get_snapshot('mods')
    assert json.loads(snapshot.responses['mods']) == [1]
    assert json.loads(snapshot.responses['mods_all']) == [1,2]
    assert snapshot.count == 2 and snapshot.last_updated == 1000


def test_mod_scores_share_one_snapshot_time(session, monkeypatch):
    manager = SnapshotCache()
    calls = []
    monkeypatch.setattr(cache.time, 'time', lambda: 1_800_000_000)
    original = cache.calculate_recommendation_score
    def record(mod, *, now):
        calls.append((mod.thread_meta.tid, now))
        return original(mod, now=now)
    monkeypatch.setattr(cache, 'calculate_recommendation_score', record)
    assert manager.refresh(session) == {'mods': True, 'games': True}
    snapshot = manager.get_snapshot('mods')
    assert calls == [(tid, snapshot.last_updated) for tid in [1, 2, 3, 4]]
    assert snapshot.last_updated == 1_800_000_000
    full = {m['thread_meta']['tid']: m for m in json.loads(snapshot.responses['mods_all'])}
    for item in json.loads(snapshot.responses['mods']):
        assert item == full[item['thread_meta']['tid']]


def test_mod_scores_change_only_after_refresh(session, monkeypatch):
    manager = SnapshotCache()
    # Fixture date is midnight UTC+8, 2026-09-12.
    start = 1_789_142_400
    monkeypatch.setattr(cache.time, 'time', lambda: start)
    assert manager.refresh(session)['mods']
    before = manager.get_response('mods', 'mods')
    monkeypatch.setattr(cache.time, 'time', lambda: start + int(7.5 * 86400))
    assert manager.get_response('mods', 'mods') == before
    assert manager.refresh(session)['mods']
    after = manager.get_response('mods', 'mods')
    assert json.loads(before)[0]['mod_recommendation_score'] == 5
    assert json.loads(after)[0]['mod_recommendation_score'] == pytest.approx(1.25)


@pytest.mark.parametrize('bad', ['raise', math.nan, math.inf, -math.inf, -1])
def test_scoring_failure_keeps_entire_mod_snapshot(session, monkeypatch, bad):
    manager = SnapshotCache()
    assert manager.refresh(session)['mods']
    previous = manager.get_snapshot('mods')
    original = cache.calculate_recommendation_score
    def broken(mod, *, now):
        if mod.thread_meta.tid == 2:
            if bad == 'raise':
                raise ValueError('scoring failed')
            return bad
        return original(mod, now=now)
    monkeypatch.setattr(cache, 'calculate_recommendation_score', broken)
    assert manager.refresh(session) == {'mods': False, 'games': True}
    assert manager.get_snapshot('mods') is previous
    assert manager.get_status()['mods']['last_updated'] == previous.last_updated


def indexed_mod(manager, tid=1):
    return next(m for m in json.loads(manager.get_response('mods', 'mods_all'))
                if m['thread_meta']['tid'] == tid)


def mapping(session, aids, tid=1):
    option = session.get(ForumTypeOptionVar, (1, tid, 46 if tid == 1 else 71, 39))
    option.value = json.dumps([{'aid': aid, 'gameVersion': 'modVersion_098x', 'modVersion': '1'}
                               for aid in aids])
    session.commit()


def assert_reconciles(item):
    releases = {r['attachment_id']: r['download_count'] for r in item['mod_releases'] or []
                if r['download_count'] is not None and r['download_count'] >= 0}
    assert sum(releases.values()) + item['mod_excluded_download_count'] == item['mod_download_count']
    assert 'mod_download_counts_by_game_version' not in item


def test_frozen_removed_file_new_file_and_reentry(session, monkeypatch):
    manager = SnapshotCache()
    source = ForumAttachment(aid=123, tid=1, downloads=1000, tableid=0)
    session.add(source)
    session.commit()
    assert manager.refresh(session)['mods']
    assert indexed_mod(manager)['mod_download_count'] == 1000
    mapping(session, [])
    mapping(session, [], tid=4)
    source.downloads = 1100
    session.commit()
    observed_statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        observed_statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', record)
    try:
        assert manager.refresh(session)['mods']
    finally:
        event.remove(session.bind, 'before_cursor_execute', record)
    # With every release removed, the forum attachment table is not queried at all.
    assert not any('pre_forum_attachment' in statement for statement in observed_statements)
    item = indexed_mod(manager)
    assert (item['mod_download_count'], item['mod_excluded_download_count']) == (1000, 1000)
    assert_reconciles(item)
    session.add(ForumAttachment(aid=124, tid=1, downloads=700, tableid=0))
    session.commit()
    mapping(session, [124])
    assert manager.refresh(session)['mods']
    item = indexed_mod(manager)
    assert (item['mod_download_count'], item['mod_excluded_download_count']) == (1700, 1000)
    assert_reconciles(item)
    mapping(session, [123, 124])
    assert manager.refresh(session)['mods']
    item = indexed_mod(manager)
    assert (item['mod_download_count'], item['mod_excluded_download_count']) == (1800, 0)
    assert_reconciles(item)


def test_source_count_regression_and_deletion_reconcile(session):
    manager = SnapshotCache()
    source = ForumAttachment(aid=123, tid=1, downloads=700, tableid=0)
    session.add(source)
    session.commit()
    assert manager.refresh(session)['mods']
    for count, excluded in [(650, 50), (680, 20), (700, 0), (710, 0)]:
        source.downloads = count
        session.commit()
        assert manager.refresh(session)['mods']
        item = indexed_mod(manager)
        assert item['mod_download_count'] == max(700, count)
        assert item['mod_excluded_download_count'] == excluded
        assert item['mod_releases'][0]['download_count'] == count
        assert_reconciles(item)
    session.delete(source)
    session.commit()
    assert manager.refresh(session)['mods']
    item = indexed_mod(manager)
    assert item['mod_download_count'] == item['mod_excluded_download_count'] == 710
    assert item['mod_releases'][0]['download_count'] is None
    assert_reconciles(item)


def test_encoding_failure_rolls_back_download_delta(session, monkeypatch):
    manager = SnapshotCache()
    source = ForumAttachment(aid=123, tid=1, downloads=1000, tableid=0)
    session.add(source)
    session.commit()
    assert manager.refresh(session)['mods']
    old = manager.get_snapshot('mods')
    source.downloads = 1100
    session.commit()
    with monkeypatch.context() as patch:
        patch.setattr(cache, '_encode', lambda _: (_ for _ in ()).throw(ValueError('encode')))
        assert manager.refresh(session) == {'mods': False, 'games': True}
    assert manager.get_snapshot('mods') is old
    with manager.stats_store.write_transaction() as connection:
        assert manager.stats_store.get_mod_summaries(connection, [1])[1]['mod_download_count'] == 1000
    assert manager.refresh(session)['mods']
    assert indexed_mod(manager)['mod_download_count'] == 1100


def test_negative_excluded_rejects_refresh_without_masking(session, monkeypatch):
    manager = SnapshotCache()
    source = ForumAttachment(aid=123, tid=1, downloads=100, tableid=0)
    session.add(source)
    session.commit()
    assert manager.refresh(session)['mods']
    old = manager.get_snapshot('mods')
    source.downloads = 110
    session.commit()
    original = manager.stats_store.get_mod_summaries
    def corrupted(connection, tids):
        result = original(connection, tids)
        result[1]['mod_download_count'] = 99
        return result
    with monkeypatch.context() as patch:
        patch.setattr(manager.stats_store, 'get_mod_summaries', corrupted)
        assert not manager.refresh(session)['mods']
    assert manager.get_snapshot('mods') is old
    with manager.stats_store.write_transaction() as connection:
        assert original(connection, [1])[1]['mod_download_count'] == 100


def test_statistics_unavailable_keeps_snapshot_and_games_refresh(session, monkeypatch):
    manager = SnapshotCache()
    assert manager.refresh(session)['mods']
    old = manager.get_snapshot('mods')
    def unavailable():
        raise OSError('statistics unavailable')
    monkeypatch.setattr(manager.stats_store, 'write_transaction', unavailable)
    assert manager.refresh(session) == {'mods': False, 'games': True}
    assert manager.get_snapshot('mods') is old


def test_startup_requires_statistics_initialization(monkeypatch):
    def unavailable():
        raise OSError('cannot open statistics storage')
    monkeypatch.setattr(main.snapshot_cache.stats_store, 'initialize', unavailable)
    with pytest.raises(OSError, match='statistics storage'):
        with TestClient(main.app):
            pass


def test_commit_without_publication_is_safe_on_next_refresh(session):
    manager = SnapshotCache()
    session.add(ForumAttachment(aid=123, tid=1, downloads=100, tableid=0))
    session.commit()
    # Fetch commits the ledger, but deliberately do not publish its snapshot.
    manager._fetch_mods(session)
    assert manager.get_response('mods', 'mods_all') == b'[]'
    restarted = SnapshotCache(DownloadStatsStore(manager.stats_store.path))
    assert restarted.refresh(session)['mods']
    assert indexed_mod(restarted)['mod_download_count'] == 100
    assert_reconciles(indexed_mod(restarted))


def test_new_fields_openapi_and_no_statistics_route():
    schema = main.app.openapi()
    for name in ['ModInfoOriginal', 'ModInfoTranslated', 'ModInfoReposted']:
        fields = schema['components']['schemas'][name]['properties']
        for key in ['mod_download_count', 'mod_excluded_download_count']:
            assert fields[key]['minimum'] == 0
        assert 'mod_download_counts_by_game_version' not in fields
    assert 'ModGameVersionDownloadCount' not in schema['components']['schemas']
    assert not any('downloads' in path for path in schema['paths'])


def test_scoring_failure_rolls_back_new_contribution(session, monkeypatch):
    manager = SnapshotCache()
    source = ForumAttachment(aid=123, tid=1, downloads=100, tableid=0)
    session.add(source)
    session.commit()
    assert manager.refresh(session)['mods']
    old = manager.get_snapshot('mods')
    source.downloads = 120
    session.commit()
    original = cache.calculate_recommendation_score
    def fail_after_first_mod(mod, *, now):
        if mod.thread_meta.tid == 2:
            raise ValueError('score unavailable')
        return original(mod, now=now)
    with monkeypatch.context() as patch:
        patch.setattr(cache, 'calculate_recommendation_score', fail_after_first_mod)
        assert not manager.refresh(session)['mods']
    assert manager.get_snapshot('mods') is old
    with manager.stats_store.write_transaction() as connection:
        assert manager.stats_store.get_mod_summaries(connection, [1])[1]['mod_download_count'] == 100
    assert manager.refresh(session)['mods']
    assert indexed_mod(manager)['mod_download_count'] == 120


def test_modding_statistics_share_full_snapshot_without_affecting_default(session):
    manager = SnapshotCache()
    session.add(ForumAttachment(aid=125, tid=4, downloads=500, tableid=0))
    session.commit()
    mapping(session, [125], tid=4)
    assert manager.refresh(session)['mods']
    item = indexed_mod(manager, 4)
    assert item['mod_download_count'] == 500
    assert_reconciles(item)
    assert all(m['thread_meta']['tid'] != 4 for m in json.loads(manager.get_response('mods', 'mods')))


def test_version_breakdown_stays_internal(session):
    manager = SnapshotCache()
    session.add(ForumAttachment(aid=123, tid=1, downloads=1000, tableid=0))
    session.commit()
    assert manager.refresh(session)['mods']
    with manager.stats_store.write_transaction() as connection:
        summary = manager.stats_store.get_mod_summaries(connection, [1])[1]
    assert summary['mod_download_count'] == 1000
    assert sum(row['download_count'] for row in
               summary['mod_download_counts_by_game_version']) == 1000
    for response in ['mods', 'mods_all']:
        items = json.loads(manager.get_response('mods', response))
        assert items
        assert all('mod_download_counts_by_game_version' not in item for item in items)
