"""First formal-index observations, in the snapshot's existing SQLite transaction."""


def initialize_schema(connection) -> None:
    # Additive extension: legacy v1 writers ignore these tables and remain compatible.
    # Schema setup is NOT baseline initialization; only a successful Mod refresh does that.
    connection.execute("""CREATE TABLE IF NOT EXISTS mod_index_state (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        initialized_at INTEGER NOT NULL
            CHECK(typeof(initialized_at) = 'integer' AND initialized_at > 0))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS mod_index_times (
        tid INTEGER PRIMARY KEY CHECK(tid > 0),
        indexed_at INTEGER CHECK(indexed_at IS NULL OR
            (typeof(indexed_at) = 'integer' AND indexed_at > 0)))""")
    connection.execute('SELECT singleton,initialized_at FROM mod_index_state LIMIT 0')
    connection.execute('SELECT tid,indexed_at FROM mod_index_times LIMIT 0')


def observe_index_times(connection, tids: list[int], formal_tids: list[int], *,
                        now: int) -> dict[int, int | None]:
    """Insert once by tid; persist NULL baseline and never infer a historical date.

    Caller owns BEGIN/COMMIT, including download observations and response encoding.
    An empty first successful snapshot still establishes the one-time baseline.
    """
    if type(now) is not int or not 0 < now < (1 << 63):
        raise ValueError('Invalid index observation timestamp')
    if (any(type(tid) is not int or tid <= 0 for tid in tids)
            or len(set(tids)) != len(tids) or len(set(formal_tids)) != len(formal_tids)
            or not set(formal_tids).issubset(tids)):
        raise ValueError('Invalid or duplicate Mod index thread IDs')
    baseline = connection.execute(
        'SELECT 1 FROM mod_index_state WHERE singleton=1').fetchone() is None
    connection.executemany("""INSERT INTO mod_index_times(tid,indexed_at) VALUES(?,?)
        ON CONFLICT(tid) DO NOTHING""",
        [(tid, None if baseline else now) for tid in formal_tids])
    if baseline:
        connection.execute(
            'INSERT INTO mod_index_state(singleton,initialized_at) VALUES(1,?)', (now,))
    result = dict.fromkeys(tids)
    for start in range(0, len(tids), 400):
        batch = tids[start:start + 400]
        placeholders = ','.join('?' for _ in batch)
        for row in connection.execute(
                f'SELECT tid,indexed_at FROM mod_index_times WHERE tid IN ({placeholders})', batch):
            result[row['tid']] = row['indexed_at']
    return result
