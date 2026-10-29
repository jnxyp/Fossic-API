"""First-index semantics, v1 additive upgrade, and snapshot transaction boundaries."""
from contextlib import closing
import json
import sqlite3

import pytest
from pydantic import ValidationError

import cache
from cache import SnapshotCache
from config import CONFIG
from download_stats import DownloadStatsStore, SCHEMA
from mod_index_time import observe_index_times
from models import ModInfoOriginal, ModInfoTranslated, ModInfoReposted
from test_mod_recommendation import mod, NOW
from test_download_stats import file


def item(tid, *, modding=False, kind=ModInfoOriginal):
    value = mod(mod_releases=[file(tid, 10)]).model_dump()
    value.update(mod_info_type=kind.model_fields['mod_info_type'].default, mod_name_en='test')
    value['thread_meta'].update(tid=tid, fid=next(iter(CONFIG['fossic'][
        'modding_fids' if modding else 'mod_fids'])))
    return kind.model_validate(value)


def observe(store, tids, formal, now=NOW):
    with store.write_transaction() as connection:
        return observe_index_times(connection, tids, formal, now=now)


def read(store, table):
    with closing(store._connect()) as connection:
        return [tuple(row) for row in connection.execute('SELECT * FROM ' + table)]


def test_baseline_null_is_durable_but_modding_is_not_baselined(isolated_download_stats):
    store = isolated_download_stats
    assert observe(store, [1, 2], [1]) == {1: None, 2: None}
    assert read(store, 'mod_index_times') == [(1, None)]
    reopened = DownloadStatsStore(store.path)
    reopened.initialize()
    assert observe(reopened, [1, 2], [1, 2], NOW + 300) == {1: None, 2: NOW + 300}
    assert read(store, 'mod_index_state') == [(1, NOW)]


def test_empty_first_snapshot_initializes_once(isolated_download_stats):
    store = isolated_download_stats
    assert observe(store, [], []) == {}
    store.initialize()
    assert observe(store, [1], [1], NOW + 300) == {1: NOW + 300}


def test_modding_only_first_snapshot_then_direct_and_promoted(isolated_download_stats):
    store = isolated_download_stats
    assert observe(store, [1], []) == {1: None}
    assert observe(store, [1, 2], [1, 2], NOW + 300) == {1: NOW + 300, 2: NOW + 300}


def test_reentry_and_absence_never_reset_timestamp_or_null(isolated_download_stats):
    store = isolated_download_stats
    observe(store, [1], [1])
    observe(store, [1, 2], [1, 2], NOW + 300)
    assert observe(store, [1, 2], [], NOW + 600) == {1: None, 2: NOW + 300}
    observe(store, [], [], NOW + 900)
    assert observe(store, [1, 2], [1, 2], NOW + 1200) == {1: None, 2: NOW + 300}


def test_batched_reads(isolated_download_stats):
    store = isolated_download_stats
    observe(store, [], [])
    tids = list(range(1, 1202))
    assert observe(store, tids, tids, NOW + 300) == dict.fromkeys(tids, NOW + 300)


@pytest.mark.parametrize('now', [0, -1, True, 1.5, '1', 1 << 63])
def test_invalid_observation_time_rolls_back(isolated_download_stats, now):
    with pytest.raises(ValueError):
        observe(isolated_download_stats, [1], [1], now)
    assert read(isolated_download_stats, 'mod_index_state') == []


@pytest.mark.parametrize('tids,formal', [([1, 1], [1]), ([1], [2]), ([1], [1, 1]),
                                        ([0], [0]), ([True], [True])])
def test_invalid_thread_set_rolls_back(isolated_download_stats, tids, formal):
    with pytest.raises(ValueError):
        observe(isolated_download_stats, tids, formal)
    assert read(isolated_download_stats, 'mod_index_times') == []


@pytest.mark.parametrize('kind', [ModInfoOriginal, ModInfoTranslated, ModInfoReposted])
def test_models_expose_nullable_strict_timestamp(kind):
    value = item(1, kind=kind).model_dump()
    assert value['mod_indexed_at'] is None
    assert kind.model_validate({**value, 'mod_indexed_at': NOW}).mod_indexed_at == NOW
    for bad in [0, -1, True, '123', 1.5]:
        with pytest.raises(ValidationError):
            kind.model_validate({**value, 'mod_indexed_at': bad})
    schema = kind.model_json_schema()['properties']['mod_indexed_at']
    assert schema['default'] is None
    assert {v['type'] for v in schema['anyOf']} == {'integer', 'null'}


def manager_with_source(monkeypatch, store, source):
    class DAO:
        def __init__(self, session):
            pass
        def get_all_mods(self):
            return source
        def get_game_versions(self):
            return []
        def get_mod_languages(self):
            return {}
        def get_mod_categories(self):
            return {}
    monkeypatch.setattr(cache, 'ModDAO', DAO)
    manager = SnapshotCache(store)
    monkeypatch.setattr(manager, '_fetch_games', lambda _: manager.get_snapshot('games'))
    return manager


def response(manager, full=False):
    return {m['thread_meta']['tid']: m for m in json.loads(
        manager.get_response('mods', 'mods_all' if full else 'mods'))}


def test_real_snapshot_types_views_edits_reentry_and_restart(isolated_download_stats, monkeypatch):
    store = isolated_download_stats
    source = [item(1), item(2, modding=True)]
    manager = manager_with_source(monkeypatch, store, source)
    monkeypatch.setattr(cache.time, 'time', lambda: NOW)
    assert manager.refresh(object())['mods']
    assert response(manager)[1]['mod_indexed_at'] is None
    assert response(manager, True)[2]['mod_indexed_at'] is None
    source[1].thread_meta.fid = source[0].thread_meta.fid
    source.extend([item(3, kind=ModInfoTranslated), item(4, kind=ModInfoReposted)])
    monkeypatch.setattr(cache.time, 'time', lambda: NOW + 300)
    assert manager.refresh(object())['mods']
    for tid in [2, 3, 4]:
        assert response(manager)[tid]['mod_indexed_at'] == NOW + 300
        assert response(manager)[tid] == response(manager, True)[tid]
    source[1].mod_id = 'changed'
    source[1].mod_name_cn = 'edited'
    source[1].mod_update_date = NOW + 999
    source[1].mod_version = '2'
    source[1].mod_releases = []
    source[1].thread_meta.fid = next(iter(CONFIG['fossic']['modding_fids']))
    monkeypatch.setattr(cache.time, 'time', lambda: NOW + 600)
    assert manager.refresh(object())['mods']
    assert 2 not in response(manager)
    assert response(manager, True)[2]['mod_indexed_at'] == NOW + 300
    # Reopen persistent state and promote again, preserving both NULL and timestamp.
    reopened = DownloadStatsStore(store.path)
    reopened.initialize()
    manager = manager_with_source(monkeypatch, reopened, source)
    source[1].thread_meta.fid = source[0].thread_meta.fid
    assert manager.refresh(object())['mods']
    assert response(manager)[1]['mod_indexed_at'] is None
    assert response(manager)[2]['mod_indexed_at'] == NOW + 300


def test_failed_first_refresh_rolls_back_baseline_downloads_and_publication(
        isolated_download_stats, monkeypatch):
    store = isolated_download_stats
    source = [item(1)]
    manager = manager_with_source(monkeypatch, store, source)
    original = cache._encode
    def fail(_):
        raise ValueError('encoding failed')
    monkeypatch.setattr(cache, '_encode', fail)
    before = manager.get_snapshot('mods')
    assert not manager.refresh(object())['mods']
    assert manager.get_snapshot('mods') is before
    for table in ['mod_index_state', 'mod_index_times', 'mod_download_totals']:
        assert read(store, table) == []
    monkeypatch.setattr(cache, '_encode', original)
    assert manager.refresh(object())['mods']
    assert response(manager)[1]['mod_indexed_at'] is None


def test_failed_later_refresh_rolls_back_new_time_and_download_increment(
        isolated_download_stats, monkeypatch):
    store = isolated_download_stats
    source = [item(1)]
    manager = manager_with_source(monkeypatch, store, source)
    monkeypatch.setattr(cache.time, 'time', lambda: NOW)
    assert manager.refresh(object())['mods']
    before = manager.get_snapshot('mods')
    tables = ['mod_index_state', 'mod_index_times', 'mod_download_totals',
              'mod_download_attachments', 'mod_download_attachment_stats']
    previous = {t: read(store, t) for t in tables}
    source.append(item(2))
    source[0].mod_releases[0].download_count += 10
    original = cache._encode
    def fail(_):
        raise ValueError('encoding failed')
    monkeypatch.setattr(cache, '_encode', fail)
    monkeypatch.setattr(cache.time, 'time', lambda: NOW + 300)
    assert not manager.refresh(object())['mods']
    assert manager.get_snapshot('mods') is before
    assert {t: read(store, t) for t in tables} == previous
    monkeypatch.setattr(cache, '_encode', original)
    monkeypatch.setattr(cache.time, 'time', lambda: NOW + 600)
    assert manager.refresh(object())['mods']
    assert response(manager)[2]['mod_indexed_at'] == NOW + 600
    assert response(manager)[1]['mod_download_count'] == 20


def test_upgrade_existing_v1_backup_and_legacy_writer_compatibility(tmp_path):
    path = tmp_path / 'v1.sqlite3'
    with closing(sqlite3.connect(path)) as connection:
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute('PRAGMA user_version=1')
        connection.execute('INSERT INTO mod_download_totals VALUES(1,0,?,?)', (NOW, NOW))
        connection.commit()
    store = DownloadStatsStore(path)
    store.initialize()
    assert read(store, 'mod_download_totals') == [(1, 0, NOW, NOW)]
    assert read(store, 'mod_index_state') == []
    observe(store, [1], [1])
    observe(store, [1, 2], [1, 2], NOW + 300)
    # The previous v1 writer checks version and original tables, not an exact table list.
    with store.write_transaction() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
        connection.execute('UPDATE mod_download_totals SET last_observed_at=?', (NOW + 600,))
    store.initialize()
    assert observe(store, [1, 2], [1, 2], NOW + 900) == {1: None, 2: NOW + 300}
    backup = tmp_path / 'backup.sqlite3'
    store.backup_to(backup)
    restored = DownloadStatsStore(backup)
    restored.initialize()
    for table in ['mod_index_state', 'mod_index_times', 'mod_download_totals']:
        assert read(restored, table) == read(store, table)


def test_openapi_three_types_have_nullable_timestamp():
    import main
    schemas = main.app.openapi()['components']['schemas']
    for name in ['ModInfoOriginal', 'ModInfoTranslated', 'ModInfoReposted']:
        field = schemas[name]['properties']['mod_indexed_at']
        assert {v['type'] for v in field['anyOf']} == {'integer', 'null'}


def test_commit_before_publication_can_be_reobserved_without_reset(isolated_download_stats):
    store = isolated_download_stats
    observe(store, [], [])
    # Simulate process exit after the transaction committed but before memory publication.
    observe(store, [1], [1], NOW + 300)
    reopened = DownloadStatsStore(store.path)
    reopened.initialize()
    assert observe(reopened, [1], [1], NOW + 600) == {1: NOW + 300}
