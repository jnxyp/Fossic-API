"""Synthetic rating/guest ACL tables for existing full-list integration fixtures."""
from sqlalchemy import text


def create_rating_schema(session):
    # These are existing production columns, not a production schema migration.
    for column in ('readperm', 'price', 'special', 'recommend_add', 'recommend_sub'):
        session.execute(text(f'ALTER TABLE pre_forum_thread ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0'))
    for ddl in [
        'CREATE TABLE pre_forum_modrating_summary(tid INTEGER PRIMARY KEY, rating_count INTEGER, display_score NUMERIC, algorithm_version INTEGER DEFAULT 2)',
        "CREATE TABLE pre_forum_forum(fid INTEGER PRIMARY KEY, fup INTEGER, type TEXT, status INTEGER DEFAULT 1)",
        "CREATE TABLE pre_forum_forumfield(fid INTEGER PRIMARY KEY, password TEXT DEFAULT '', viewperm TEXT DEFAULT '', formulaperm TEXT DEFAULT '', price INTEGER DEFAULT 0)",
        'CREATE TABLE pre_common_usergroup_field(groupid INTEGER PRIMARY KEY, readaccess INTEGER)',
        'INSERT INTO pre_common_usergroup_field VALUES(7,10)',
        "INSERT INTO pre_forum_forum VALUES(42,0,'group',1),(46,42,'forum',1),(60,42,'forum',1),(78,42,'forum',1),(71,42,'forum',1)",
        'INSERT INTO pre_forum_forumfield(fid) VALUES(42),(46),(60),(78),(71)',
    ]:
        session.execute(text(ddl))
