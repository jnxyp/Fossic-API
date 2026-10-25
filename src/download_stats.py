"""Persistent attachment contributions; only the snapshot refresh writes statistics."""
from contextlib import closing, contextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import os
import sqlite3
import tempfile
import time as clock

from models import ModInfoTypes, ModRelease
import log

logger = log.get_logger(__name__)
MAX_COUNT = (1 << 63) - 1
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
SCHEMA_VERSION = 1

SCHEMA = (
    """CREATE TABLE mod_download_totals (
        tid INTEGER PRIMARY KEY CHECK(tid > 0),
        total_download_count INTEGER NOT NULL DEFAULT 0
            CHECK(typeof(total_download_count) = 'integer' AND total_download_count >= 0),
        tracking_started_at INTEGER NOT NULL,
        last_observed_at INTEGER NOT NULL)""",
    """CREATE TABLE mod_download_attachments (
        tid INTEGER NOT NULL,
        attachment_id INTEGER NOT NULL CHECK(attachment_id > 0),
        game_version_id TEXT NOT NULL CHECK(length(game_version_id) > 0),
        game_version TEXT NOT NULL,
        counted_download_count INTEGER NOT NULL
            CHECK(typeof(counted_download_count) = 'integer' AND counted_download_count >= 0),
        first_observed_at INTEGER NOT NULL,
        last_observed_at INTEGER NOT NULL,
        PRIMARY KEY(tid, attachment_id),
        FOREIGN KEY(tid) REFERENCES mod_download_totals(tid))""",
    """CREATE TABLE mod_download_attachment_stats (
        tid INTEGER NOT NULL,
        attachment_id INTEGER NOT NULL,
        period_start INTEGER NOT NULL,
        period_end INTEGER NOT NULL CHECK(period_end > period_start),
        download_increment INTEGER NOT NULL
            CHECK(typeof(download_increment) = 'integer' AND download_increment >= 0),
        first_observed_at INTEGER NOT NULL,
        last_observed_at INTEGER NOT NULL,
        PRIMARY KEY(tid, attachment_id, period_start),
        FOREIGN KEY(tid, attachment_id)
            REFERENCES mod_download_attachments(tid, attachment_id))""",
    """CREATE INDEX idx_mod_download_attachments_version
        ON mod_download_attachments(tid, game_version_id)""",
    """CREATE INDEX idx_mod_download_stats_period
        ON mod_download_attachment_stats(tid, period_start)""",
)


def checked_count(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ValueError('Download contribution outside SQLite integer range')
    return value


def current_releases(releases: list[ModRelease] | None) -> dict[int, ModRelease]:
    """One mapping per aid; conflicting data must never publish a partial ledger."""
    result = {}
    for release in releases or []:
        aid = release.attachment_id
        if type(aid) is not int or aid <= 0:
            raise ValueError('Invalid attachment ID')
        previous = result.get(aid)
        if previous is not None and (
            previous.game_version_id != release.game_version_id
            or previous.game_version != release.game_version
            or previous.download_count != release.download_count
        ):
            raise ValueError('Conflicting attachment mapping or count')
        result[aid] = release
    return result


def get_stats_period(now: int) -> tuple[int, int]:
    """Initial policy: Beijing calendar day, represented as [start, end) UTC seconds."""
    date = datetime.fromtimestamp(now, BEIJING).date()
    start = datetime.combine(date, time(), tzinfo=BEIJING)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


class DownloadStatsStore:
    def __init__(self, path: str | Path, *, timeout: float = 5.0):
        self.path = Path(path).resolve()
        self.timeout = timeout

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        # Normal refreshes must not silently recreate a removed statistics file.
        uri = self.path.as_uri() + ('?mode=rwc' if create else '?mode=rw')
        connection = sqlite3.connect(uri, uri=True, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
        except BaseException:
            connection.close()
            raise
        return connection

    def initialize(self) -> None:
        # Parent directory must be explicitly provisioned with the service UID/GID.
        with closing(self._connect(create=True)) as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError('Unsupported download statistics schema version')
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Invalid download statistics database')
            if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                raise ValueError('Download statistics require WAL mode')
            connection.execute('BEGIN IMMEDIATE')
            try:
                # Recheck under the writer lock before touching the schema.
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version == 0:
                    if connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone():
                        raise ValueError('Refusing to initialize a nonempty unversioned database')
                    for statement in SCHEMA:
                        connection.execute(statement)
                    connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
                elif version != SCHEMA_VERSION:
                    raise ValueError('Unsupported download statistics schema version')
                for table, columns in (
                    ('mod_download_totals', 'tid,total_download_count,tracking_started_at,last_observed_at'),
                    ('mod_download_attachments', 'tid,attachment_id,game_version_id,game_version,'
                        'counted_download_count,first_observed_at,last_observed_at'),
                    ('mod_download_attachment_stats', 'tid,attachment_id,period_start,period_end,'
                        'download_increment,first_observed_at,last_observed_at'),
                ):
                    connection.execute(f'SELECT {columns} FROM {table} LIMIT 0')
                if connection.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('Invalid download statistics references')
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def write_transaction(self):
        with closing(self._connect()) as connection:
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise ValueError('Unsupported download statistics schema version')
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _rows(connection, table: str, tids: list[int]):
        # Table identifiers are internal constants, never request parameters.
        for start in range(0, len(tids), 400):
            batch = tids[start:start + 400]
            placeholders = ','.join('?' for _ in batch)
            yield from connection.execute(
                f'SELECT * FROM {table} WHERE tid IN ({placeholders})', batch)

    def apply_observations(self, connection, mods: list[ModInfoTypes], *, now: int) -> None:
        tids = [mod.thread_meta.tid for mod in mods]
        if len(set(tids)) != len(tids):
            raise ValueError('Duplicate Mod thread ID')
        ledger = {(row['tid'], row['attachment_id']): row
                  for row in self._rows(connection, 'mod_download_attachments', tids)}
        totals = {row['tid']: row['total_download_count']
                  for row in self._rows(connection, 'mod_download_totals', tids)}
        period_start, period_end = get_stats_period(now)
        for mod in mods:
            tid = mod.thread_meta.tid
            total = checked_count(totals.get(tid, 0))
            connection.execute("""INSERT INTO mod_download_totals
                (tid,total_download_count,tracking_started_at,last_observed_at) VALUES(?,?,?,?)
                ON CONFLICT(tid) DO UPDATE SET last_observed_at=excluded.last_observed_at""",
                (tid, total, now, now))
            # No source reads for historical files: only current registered releases are observed.
            for aid, release in current_releases(mod.mod_releases).items():
                count = release.download_count
                if count is None or type(count) is not int or count < 0:
                    continue
                checked_count(count)
                if not release.game_version_id:
                    raise ValueError('Missing attachment game version')
                previous = ledger.get((tid, aid))
                old = previous['counted_download_count'] if previous else 0
                delta = max(0, count - old)
                total = checked_count(total + delta)
                if count < old:
                    logger.warning('附件计数回退，保留高水位: tid=%s aid=%s', tid, aid)
                connection.execute("""INSERT INTO mod_download_attachments
                    (tid,attachment_id,game_version_id,game_version,counted_download_count,
                     first_observed_at,last_observed_at) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(tid,attachment_id) DO UPDATE SET
                        game_version_id=excluded.game_version_id,
                        game_version=excluded.game_version,
                        counted_download_count=excluded.counted_download_count,
                        last_observed_at=excluded.last_observed_at""",
                    (tid, aid, release.game_version_id, release.game_version, max(old, count), now, now))
                # Reject overlap, including same start with a changed end, rather than merging policies.
                if connection.execute("""SELECT 1 FROM mod_download_attachment_stats
                    WHERE tid=? AND attachment_id=? AND period_start < ? AND period_end > ?
                    AND NOT(period_start=? AND period_end=?) LIMIT 1""",
                    (tid, aid, period_end, period_start, period_start, period_end)).fetchone():
                    raise ValueError('Overlapping download statistics periods')
                connection.execute("""INSERT INTO mod_download_attachment_stats
                    (tid,attachment_id,period_start,period_end,download_increment,
                     first_observed_at,last_observed_at) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(tid,attachment_id,period_start) DO UPDATE SET
                        download_increment=download_increment+excluded.download_increment,
                        last_observed_at=excluded.last_observed_at""",
                    (tid, aid, period_start, period_end, delta, now, now))
            connection.execute('UPDATE mod_download_totals SET total_download_count=? WHERE tid=?',
                               (total, tid))

    def get_mod_summaries(self, connection, tids: list[int]) -> dict[int, dict]:
        totals = {row['tid']: checked_count(row['total_download_count'])
                  for row in self._rows(connection, 'mod_download_totals', tids)}
        versions = {tid: {} for tid in totals}
        names = {}
        for row in self._rows(connection, 'mod_download_attachments', tids):
            key = (row['tid'], row['game_version_id'])
            if key not in names or row['last_observed_at'] > names[key][0]:
                names[key] = (row['last_observed_at'], row['game_version'])
            grouped = versions[row['tid']]
            version = grouped.setdefault(row['game_version_id'], {
                'game_version_id': row['game_version_id'], 'game_version': row['game_version'],
                'download_count': 0})
            version['download_count'] = checked_count(
                version['download_count'] + row['counted_download_count'])
        # Aggregate in SQL, not by loading the entire period history into Python.
        period_totals = {}
        for start in range(0, len(tids), 400):
            batch = tids[start:start + 400]
            placeholders = ','.join('?' for _ in batch)
            for row in connection.execute(f"""SELECT tid,SUM(download_increment) AS total
                FROM mod_download_attachment_stats WHERE tid IN ({placeholders}) GROUP BY tid""", batch):
                period_totals[row['tid']] = checked_count(row['total'])
        result = {}
        for tid, total in totals.items():
            items = [dict(versions[tid][key], game_version=names[(tid, key)][1])
                     for key in sorted(versions[tid])]
            if total != sum(item['download_count'] for item in items) or total != period_totals.get(tid, 0):
                raise ValueError('Download statistics totals do not reconcile')
            result[tid] = {'mod_download_count': total,
                          'mod_download_counts_by_game_version': items}
        return result

    def backup_to(self, destination: str | Path) -> None:
        """Create a validated, single-file backup; replace an older backup only on success."""
        target = Path(destination).resolve()
        if target == self.path:
            raise ValueError('Backup destination must differ from the live database')
        if target.exists() and self.path.exists() and os.path.samefile(target, self.path):
            raise ValueError('Backup destination aliases the live database')
        # Never replace a live SQLite destination with outstanding journal sidecars.
        if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Backup destination has SQLite journal sidecars')
        fd, name = tempfile.mkstemp(prefix=target.name + '.', suffix='.tmp', dir=target.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            deadline = clock.monotonic() + 120
            def progress(status, remaining, total):
                if clock.monotonic() > deadline:
                    raise TimeoutError('Download statistics backup timed out')
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                        timeout=self.timeout)) as source:
                if source.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                    raise ValueError('Unsupported download statistics schema version')
                with closing(sqlite3.connect(temporary)) as output:
                    source.backup(output, pages=128, progress=progress, sleep=0.1)
                    if output.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('Download statistics backup failed validation')
                    if output.execute('PRAGMA foreign_key_check').fetchone():
                        raise ValueError('Download statistics backup has invalid references')
            with temporary.open('rb+') as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Consistent download statistics backup (no API calls)')
    parser.add_argument('--source', required=True, help='Existing live SQLite database')
    parser.add_argument('--backup', required=True, help='Backup path; parent must already exist')
    args = parser.parse_args()
    DownloadStatsStore(args.source).backup_to(args.backup)
