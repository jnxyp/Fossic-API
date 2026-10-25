"""Offline persistence, period boundaries, frozen files, and recovery regressions."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

import download_stats
from download_stats import DownloadStatsStore, MAX_COUNT, get_stats_period
from models import ModRelease
from test_mod_recommendation import mod, NOW


def file(aid=1, count=0, version='v98', name=None):
    return ModRelease(attachment_id=aid, download_count=count, game_version_id=version,
                      game_version=name or version, mod_version='1')


def observe(store, releases, *, now=NOW, tid=1):
    item = mod(mod_releases=releases)
    item.thread_meta.tid = tid
    with store.write_transaction() as connection:
        store.apply_observations(connection, [item], now=now)
        return store.get_mod_summaries(connection, [tid])[tid]


def rows(store, table):
    with closing(store._connect()) as connection:
        return [dict(row) for row in connection.execute('SELECT * FROM ' + table)]


def total(store, releases, **kwargs):
    return observe(store, releases, **kwargs)['mod_download_count']


def assert_consistent(store, tid=1):
    with store.write_transaction() as connection:
        summary = store.get_mod_summaries(connection, [tid])[tid]
        assert summary['mod_download_count'] == sum(
            row['download_count'] for row in summary['mod_download_counts_by_game_version'])
        return summary


def test_first_observation_existing_counts_and_idempotent_reopen(isolated_download_stats):
    store = isolated_download_stats
    assert total(store, [file(1, 1000), file(2, 25)]) == 1025
    assert total(store, [file(1, 1000), file(2, 25)], now=NOW+300) == 1025
    reopened = DownloadStatsStore(store.path)
    reopened.initialize()
    assert total(reopened, [file(1, 1005), file(2, 25)], now=NOW+600) == 1030
    assert sum(row['download_increment'] for row in rows(store, 'mod_download_attachment_stats')) == 1030
    assert all(row['first_observed_at'] == NOW for row in rows(store, 'mod_download_attachments'))


def test_exit_freezes_and_reentry_adds_only_difference(isolated_download_stats):
    store = isolated_download_stats
    assert total(store, [file(1, 1000)]) == 1000
    before = rows(store, 'mod_download_attachments')
    stats = rows(store, 'mod_download_attachment_stats')
    assert total(store, [], now=NOW+300) == 1000
    assert total(store, None, now=NOW+86400) == 1000
    assert rows(store, 'mod_download_attachments') == before
    assert rows(store, 'mod_download_attachment_stats') == stats
    assert total(store, [file(1, 1050)], now=NOW+86400) == 1050
    assert sorted(row['download_increment'] for row in rows(store, 'mod_download_attachment_stats')) == [50, 1000]


def test_new_old_file_adds_full_count_without_recounting_frozen_file(isolated_download_stats):
    store = isolated_download_stats
    assert total(store, [file(1, 1000)]) == 1000
    assert total(store, [file(2, 5000)], now=NOW+300) == 6000
    assert total(store, [file(2, 5005)], now=NOW+600) == 6005
    assert rows(store, 'mod_download_attachments')[0]['last_observed_at'] == NOW


@pytest.mark.parametrize('count', [None, -1, True, 1.5, '3'])
def test_invalid_observation_freezes_without_zero_period(isolated_download_stats, count):
    store = isolated_download_stats
    assert total(store, [file(1, 100)]) == 100
    dirty = file(1).model_copy(update={'download_count': count})
    assert total(store, [dirty], now=NOW+86400) == 100
    assert len(rows(store, 'mod_download_attachment_stats')) == 1
    assert rows(store, 'mod_download_attachments')[0]['last_observed_at'] == NOW


def test_zero_is_observed_but_unknown_is_not(isolated_download_stats):
    store = isolated_download_stats
    assert total(store, [file(1, 0), file(2, None)]) == 0
    assert len(rows(store, 'mod_download_attachments')) == 1
    assert rows(store, 'mod_download_attachment_stats')[0]['download_increment'] == 0
    assert total(store, [file(1, 0)], now=NOW+86400) == 0
    assert len(rows(store, 'mod_download_attachment_stats')) == 2


def test_counter_regression_preserves_high_water(isolated_download_stats, caplog):
    store = isolated_download_stats
    assert total(store, [file(1, 1000)]) == 1000
    assert total(store, [file(1, 800)], now=NOW+300) == 1000
    assert total(store, [file(1, 1000)], now=NOW+600) == 1000
    assert total(store, [file(1, 1005)], now=NOW+900) == 1005
    assert '保留高水位' in caplog.text
    assert_consistent(store)


def test_version_reclassification_and_historical_version_retention(isolated_download_stats):
    store = isolated_download_stats
    total(store, [file(1, 1000, 'v97'), file(2, 500, 'v98')])
    result = observe(store, [file(2, 500, 'v99')], now=NOW+300)
    assert result['mod_download_count'] == 1500
    assert [(r['game_version_id'], r['download_count']) for r in result['mod_download_counts_by_game_version']] == [('v97', 1000), ('v99', 500)]
    assert sum(r['download_increment'] for r in rows(store, 'mod_download_attachment_stats')) == 1500
    assert total(store, [file(2, 510, 'v99')], now=NOW+600) == 1510


def test_version_display_name_uses_most_recent_observation(isolated_download_stats):
    store = isolated_download_stats
    total(store, [file(1, 10, name='old'), file(2, 20, name='old')])
    result = observe(store, [file(2, 20, name='new')], now=NOW+300)
    assert result['mod_download_counts_by_game_version'] == [
        {'game_version_id': 'v98', 'game_version': 'new', 'download_count': 30}]


def test_duplicate_same_mapping_deduplicates(isolated_download_stats):
    assert total(isolated_download_stats, [file(1, 100), file(1, 100)]) == 100


@pytest.mark.parametrize('duplicate', [file(1, 100, 'v97'), file(1, 101), file(1, None)])
def test_conflicting_current_mapping_rolls_back_all(isolated_download_stats, duplicate):
    store = isolated_download_stats
    total(store, [file(1, 90)])
    before = rows(store, 'mod_download_attachments')
    with pytest.raises(ValueError, match='Conflicting'):
        observe(store, [file(2, 300), file(1, 100), duplicate], now=NOW+300)
    assert rows(store, 'mod_download_attachments') == before
    assert_consistent(store)


def test_threads_are_independent_even_with_same_mod_id(isolated_download_stats):
    store = isolated_download_stats
    assert total(store, [file(1, 100)], tid=1) == 100
    assert total(store, [file(2, 200)], tid=2) == 200
    with store.write_transaction() as connection:
        store.apply_observations(connection, [], now=NOW+300)
    assert [row['last_observed_at'] for row in rows(store, 'mod_download_totals')] == [NOW, NOW]
    assert total(store, [file(1, 110)], tid=1, now=NOW+600) == 110
    assert assert_consistent(store, 2)['mod_download_count'] == 200


def test_period_boundary_is_beijing_not_utc():
    boundary = int(datetime(2026, 10, 25, 16, tzinfo=timezone.utc).timestamp())
    assert get_stats_period(boundary-1) == (boundary-86400, boundary)
    assert get_stats_period(boundary) == (boundary, boundary+86400)


def test_gap_is_not_backfilled(isolated_download_stats):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    total(store, [file(1, 130)], now=NOW+3*86400)
    values = rows(store, 'mod_download_attachment_stats')
    assert len(values) == 2
    assert [r['download_increment'] for r in values] == [100, 30]
    assert values[1]['period_start'] - values[0]['period_start'] == 3*86400


@pytest.mark.parametrize('offset', [0, -3600])
def test_overlapping_periods_are_rejected(isolated_download_stats, monkeypatch, offset):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    start, end = get_stats_period(NOW)
    monkeypatch.setattr(download_stats, 'get_stats_period', lambda now: (start+offset, end+3600))
    with pytest.raises(ValueError, match='Overlapping'):
        total(store, [file(1, 120)], now=NOW+300)
    assert rows(store, 'mod_download_attachments')[0]['counted_download_count'] == 100


def test_changed_period_policy_at_boundary_can_append(isolated_download_stats, monkeypatch):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    _, boundary = get_stats_period(NOW)
    monkeypatch.setattr(download_stats, 'get_stats_period', lambda now: (boundary, boundary+3600))
    assert total(store, [file(1, 110)], now=boundary) == 110
    assert [r['period_end']-r['period_start'] for r in rows(store, 'mod_download_attachment_stats')] == [86400, 3600]


def test_exception_after_write_rolls_back_every_table(isolated_download_stats):
    store = isolated_download_stats
    with pytest.raises(RuntimeError):
        with store.write_transaction() as connection:
            store.apply_observations(connection, [mod(mod_releases=[file(1, 100)])], now=NOW)
            raise RuntimeError('encoding failed')
    for table in ('mod_download_totals', 'mod_download_attachments', 'mod_download_attachment_stats'):
        assert rows(store, table) == []


def test_committed_but_not_published_retries_without_duplication(isolated_download_stats):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    # Treat the first returned summary as lost; a new process repeats the same source read.
    assert total(DownloadStatsStore(store.path), [file(1, 100)], now=NOW+300) == 100
    assert_consistent(store)


def test_empty_mods_and_missing_files_have_no_fake_versions(isolated_download_stats):
    store = isolated_download_stats
    result = observe(store, [file(1, None)])
    assert result == {'mod_download_count': 0, 'mod_download_counts_by_game_version': []}
    assert len(rows(store, 'mod_download_totals')) == 1


def test_integer_max_and_total_overflow_roll_back(isolated_download_stats):
    store = isolated_download_stats
    assert total(store, [file(1, MAX_COUNT)]) == MAX_COUNT
    with pytest.raises(ValueError, match='integer range'):
        total(store, [file(1, MAX_COUNT), file(2, 1)], now=NOW+300)
    assert len(rows(store, 'mod_download_attachments')) == 1
    assert_consistent(store)
    with pytest.raises(ValueError, match='integer range'):
        total(store, [file(1, MAX_COUNT+1)])


def test_corrupt_totals_cannot_publish(isolated_download_stats):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    with store.write_transaction() as connection:
        connection.execute('UPDATE mod_download_totals SET total_download_count=101')
    with pytest.raises(ValueError, match='reconcile'):
        observe(store, [file(1, 100)])


def test_missing_database_not_silently_created_on_refresh(tmp_path):
    store = DownloadStatsStore(tmp_path / 'missing.sqlite3')
    with pytest.raises(sqlite3.OperationalError):
        observe(store, [])
    assert not store.path.exists()


def test_parent_directory_must_be_provisioned(tmp_path):
    store = DownloadStatsStore(tmp_path / 'missing-directory' / 'stats.sqlite3')
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()


@pytest.mark.parametrize('version', [2, 100, -1])
def test_unknown_schema_not_reset(tmp_path, version):
    path = tmp_path / 'future.sqlite3'
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f'PRAGMA user_version={version}')
    store = DownloadStatsStore(path)
    with pytest.raises(ValueError, match='schema version'):
        store.initialize()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == version


def test_nonempty_unversioned_database_not_adopted(tmp_path):
    path = tmp_path / 'foreign.sqlite3'
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE private_data (value TEXT)')
    with pytest.raises(ValueError, match='nonempty'):
        DownloadStatsStore(path).initialize()


def test_corrupted_database_rejected_without_reset(tmp_path):
    path = tmp_path / 'broken.sqlite3'
    path.write_bytes(b'not a sqlite database')
    with pytest.raises(sqlite3.DatabaseError):
        DownloadStatsStore(path).initialize()
    assert path.read_bytes() == b'not a sqlite database'


def test_schema_settings_and_foreign_keys(isolated_download_stats):
    store = isolated_download_stats
    with store.write_transaction() as connection:
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert connection.execute('PRAGMA synchronous').fetchone()[0] == 2
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
        assert connection.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("""INSERT INTO mod_download_attachment_stats VALUES(1,1,0,1,0,0,0)""")


def test_lock_timeout_does_not_commit_partial_data(isolated_download_stats):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    contender = DownloadStatsStore(store.path, timeout=0.01)
    with store.write_transaction():
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            total(contender, [file(1, 110)])
    assert_consistent(store)
    assert rows(store, 'mod_download_attachments')[0]['counted_download_count'] == 100


def test_readonly_connection_fails_without_reset(isolated_download_stats, monkeypatch):
    store = isolated_download_stats
    total(store, [file(1, 100)])
    other = DownloadStatsStore(store.path)
    def readonly(**kwargs):
        connection = sqlite3.connect(store.path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection
    monkeypatch.setattr(other, '_connect', readonly)
    with pytest.raises(sqlite3.OperationalError):
        total(other, [file(1, 110)])
    assert assert_consistent(store)['mod_download_count'] == 100


def test_backup_includes_uncheckpointed_wal_and_restores(isolated_download_stats, tmp_path):
    store = isolated_download_stats
    backup = tmp_path / 'backup.sqlite3'
    # Keep a connection open so committed WAL is not checkpointed by the last close.
    with closing(store._connect()) as keeper:
        total(store, [file(1, 100)])
        assert Path(str(store.path) + '-wal').stat().st_size > 0
        store.backup_to(backup)
        restored = DownloadStatsStore(backup)
        restored.initialize()
        assert total(restored, [file(1, 100)], now=NOW+300) == 100
        assert total(restored, [file(1, 110)], now=NOW+600) == 110
        assert assert_consistent(store)['mod_download_count'] == 100
    assert_consistent(restored)


def test_backup_replace_and_missing_source_preserve_old_backup(isolated_download_stats, tmp_path):
    store = isolated_download_stats
    backup = tmp_path / 'backup.sqlite3'
    total(store, [file(1, 100)])
    store.backup_to(backup)
    before = backup.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        DownloadStatsStore(tmp_path / 'missing.sqlite3').backup_to(backup)
    assert backup.read_bytes() == before
    assert not list(tmp_path.glob('backup.sqlite3.*.tmp'))
    total(store, [file(1, 110)])
    store.backup_to(backup)
    assert assert_consistent(DownloadStatsStore(backup))['mod_download_count'] == 110


def test_backup_rejects_live_source_or_journal_destination(isolated_download_stats, tmp_path):
    store = isolated_download_stats
    with pytest.raises(ValueError, match='differ'):
        store.backup_to(store.path)
    backup = tmp_path / 'backup.sqlite3'
    Path(str(backup) + '-wal').touch()
    with pytest.raises(ValueError, match='sidecars'):
        store.backup_to(backup)



@pytest.mark.parametrize('aid', [0, -1, True, 1.5])
def test_invalid_attachment_id_cannot_change_ledger(isolated_download_stats, aid):
    dirty = file(1, 10).model_copy(update={'attachment_id': aid})
    with pytest.raises(ValueError, match='attachment ID'):
        total(isolated_download_stats, [dirty])
    assert rows(isolated_download_stats, 'mod_download_totals') == []


def test_duplicate_thread_ids_reject_snapshot(isolated_download_stats):
    store = isolated_download_stats
    with pytest.raises(ValueError, match='Duplicate Mod'):
        with store.write_transaction() as connection:
            store.apply_observations(connection, [mod(), mod()], now=NOW)
    assert rows(store, 'mod_download_totals') == []


def test_summary_batches_more_than_sqlite_parameter_limit(isolated_download_stats):
    store = isolated_download_stats
    items = [mod(mod_releases=[]) for _ in range(1001)]
    for tid, item in enumerate(items, 1):
        item.thread_meta.tid = tid
    with store.write_transaction() as connection:
        store.apply_observations(connection, items, now=NOW)
        result = store.get_mod_summaries(connection, list(range(1, 1002)))
    assert len(result) == 1001
    assert all(item['mod_download_count'] == 0 for item in result.values())


def test_backup_timeout_keeps_previous_backup(isolated_download_stats, tmp_path, monkeypatch):
    store = isolated_download_stats
    backup = tmp_path / 'backup.sqlite3'
    total(store, [file(1, 100)])
    store.backup_to(backup)
    before = backup.read_bytes()
    ticks = iter([0, 121])
    monkeypatch.setattr(download_stats.clock, 'monotonic', lambda: next(ticks))
    with pytest.raises(TimeoutError, match='timed out'):
        store.backup_to(backup)
    assert backup.read_bytes() == before
    assert not list(tmp_path.glob('backup.sqlite3.*.tmp'))


def test_many_refreshes_match_independent_reference_model(isolated_download_stats):
    import random
    randomizer = random.Random(20261025)
    store = isolated_download_stats
    ledger, versions = {}, {}
    for step in range(100):
        active = []
        for aid in range(1, 9):
            if randomizer.random() < 0.45:
                continue
            count = randomizer.choice([None, 0, randomizer.randrange(2000)])
            version = randomizer.choice(['v97', 'v98', 'v99'])
            active.append(file(aid, count, version))
            if count is not None:
                ledger[aid] = max(ledger.get(aid, 0), count)
                versions[aid] = version
        result = observe(store, active, now=NOW+step*5000)
        assert result['mod_download_count'] == sum(ledger.values())
        expected = {}
        for aid, count in ledger.items():
            expected[versions[aid]] = expected.get(versions[aid], 0) + count
        assert {r['game_version_id']: r['download_count']
                for r in result['mod_download_counts_by_game_version']} == expected
        displayed = sum(r.download_count or 0 for r in active)
        assert result['mod_download_count'] - displayed >= 0


def test_foreign_key_corruption_prevents_initialization(isolated_download_stats):
    store = isolated_download_stats
    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute('INSERT INTO mod_download_attachment_stats VALUES(99,1,0,1,0,0,0)')
        connection.commit()
    with pytest.raises(ValueError, match='references'):
        store.initialize()
