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
        def reject(*args, **kwargs):
            raise AssertionError('request must not query or encode')
        event.listen(session.bind, 'before_cursor_execute', reject)
        try:
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
    assert json.loads(after)[0]['mod_recommendation_score'] == pytest.approx(2.5)


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
