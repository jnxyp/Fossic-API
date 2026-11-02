"""Real list refresh + guest ACL queries; no live database or rating formula copy."""
import json
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, text

import api
import cache
import main
from cache import SnapshotCache
from db import get_session
from models import ModRating
from ratings import read_rating_snapshot, read_ratings
from test_games import games
from test_mods_integration import session
from test_ratings import EMPTY_NATIVE_FORMULA


def rows(manager, full=False):
    return {m['thread_meta']['tid']: m for m in json.loads(
        manager.get_response('mods', 'mods_all' if full else 'mods'))}


def seed(session):
    session.execute(text('INSERT INTO pre_forum_modrating_summary VALUES '
                         '(1,10,4.47,2),(2,10,0,2),(3,9,NULL,2)'))
    session.commit()


def test_list_contract_all_types_modding_games_and_live_routes(games, monkeypatch):
    seed(games)
    manager = SnapshotCache()
    monkeypatch.setattr(api, 'snapshot_cache', manager)
    monkeypatch.setattr(main, 'snapshot_cache', manager)
    monkeypatch.setattr(main, 'refresh_cache', lambda: manager.refresh(games))
    main.app.dependency_overrides[get_session] = lambda: games
    try:
        with TestClient(main.app) as client:
            expected = {1: {'score': 4.47, 'count': 10},
                        2: {'score': 0.0, 'count': 10},
                        3: {'score': None, 'count': 9},
                        4: {'score': None, 'count': 0}}
            for path in ['/mods', '/mods?include_modding=true']:
                items = client.get(path).json()
                assert len(items) == (4 if 'true' in path else 3)
                for item in items:
                    tid = item['thread_meta']['tid']
                    assert item['mod_rating'] == expected[tid]
                    assert not {'recommend_weight', 'heats'} & item['thread_meta'].keys()
                    live = client.get(f'/mods/{tid}/rating')
                    assert live.headers['cache-control'] == 'no-store'
                    assert live.json() == {'score': expected[tid]['score'],
                                           'rating_count': expected[tid]['count']}
            game = client.get('/games').json()[0]
            assert 'mod_rating' not in game
            assert not {'recommend_weight', 'heats'} & game['thread_meta'].keys()
            assert {'views', 'featured_level', 'tid'} <= game['thread_meta'].keys()
            batch = client.get('/mods/ratings?tid=1&tid=2').json()
            assert batch == {'1': {'score': 4.47, 'rating_count': 10},
                             '2': {'score': 0.0, 'rating_count': 10}}
    finally:
        main.app.dependency_overrides.pop(get_session, None)


def test_score_and_count_are_snapshot_values_until_successful_refresh(session):
    seed(session)
    manager = SnapshotCache()
    assert manager.refresh(session)['mods']
    previous = manager.get_snapshot('mods')
    session.execute(text('UPDATE pre_forum_modrating_summary '
                         'SET display_score=5,rating_count=11 WHERE tid=1'))
    session.commit()
    assert rows(manager)[1]['mod_rating'] == {'score': 4.47, 'count': 10}
    assert read_ratings(session, [1])[1] == {'score': 5.0, 'rating_count': 11}
    assert manager.get_snapshot('mods') is previous
    assert manager.refresh(session)['mods']
    assert rows(manager)[1]['mod_rating'] == {'score': 5.0, 'count': 11}
    assert rows(manager)[1] == rows(manager, True)[1]


@pytest.mark.parametrize('sql', [
    'UPDATE pre_forum_thread SET readperm=20 WHERE tid=1',
    'UPDATE pre_forum_thread SET price=1 WHERE tid=1',
    "UPDATE pre_forum_forumfield SET password='private' WHERE fid=46",
    "UPDATE pre_forum_forumfield SET viewperm='17' WHERE fid=46",
    "UPDATE pre_forum_forumfield SET viewperm='17' WHERE fid=42",
    "UPDATE pre_forum_forumfield SET formulaperm='unknown' WHERE fid=46",
    "UPDATE pre_forum_forumfield SET formulaperm='unknown' WHERE fid=42",
    'UPDATE pre_forum_forumfield SET price=1 WHERE fid=42',
    'UPDATE pre_forum_forum SET status=0 WHERE fid=42',
    'UPDATE pre_forum_forum SET fup=46 WHERE fid=42',
    'DELETE FROM pre_forum_forumfield WHERE fid=42',
])
def test_private_summary_is_null_not_zero_or_leaked(session, sql):
    seed(session)
    session.execute(text(sql))
    session.commit()
    manager = SnapshotCache()
    assert manager.refresh(session)['mods']
    assert rows(manager)[1]['mod_rating'] is None
    assert rows(manager, True)[1]['mod_rating'] is None
    assert read_ratings(session, [1]) == {}


def test_canonical_empty_wrapper_is_public_for_list_and_live(session):
    seed(session)
    session.execute(text('UPDATE pre_forum_forumfield SET formulaperm=:rule'),
                    {'rule': EMPTY_NATIVE_FORMULA})
    session.commit()
    manager = SnapshotCache()
    assert manager.refresh(session)['mods']
    assert rows(manager)[1]['mod_rating'] == {'score': 4.47, 'count': 10}


@pytest.mark.parametrize('sql', [
    'UPDATE pre_forum_modrating_summary SET algorithm_version=1 WHERE tid=1',
    'UPDATE pre_forum_modrating_summary SET rating_count=-1 WHERE tid=1',
    'UPDATE pre_forum_modrating_summary SET rating_count=NULL WHERE tid=1',
    'UPDATE pre_forum_modrating_summary SET display_score=6 WHERE tid=1',
    'UPDATE pre_forum_modrating_summary SET display_score=NULL WHERE tid=1',
    'UPDATE pre_forum_modrating_summary SET display_score=1 WHERE tid=3',
    'UPDATE pre_forum_thread SET recommend_add=1 WHERE tid=4',
    'DROP TABLE pre_forum_modrating_summary',
    'DROP TABLE pre_common_usergroup_field',
])
def test_failed_rating_refresh_preserves_all_mod_bytes_and_never_writes_stats(
        session, monkeypatch, sql):
    seed(session)
    manager = SnapshotCache()
    assert manager.refresh(session)['mods']
    previous = manager.get_snapshot('mods')
    session.execute(text(sql))
    session.commit()
    monkeypatch.setattr(cache.time, 'sleep', lambda _: None)
    entered = []
    original = manager.stats_store.write_transaction
    def track_transaction():
        entered.append(True)
        return original()
    monkeypatch.setattr(manager.stats_store, 'write_transaction', track_transaction)
    assert manager.refresh(session) == {'mods': False, 'games': True}
    assert entered == []  # Rating reads finish before taking the SQLite writer lock.
    assert manager.get_snapshot('mods') is previous
    assert manager.get_status()['mods']['last_updated'] == previous.last_updated


def test_internal_bulk_chunks_share_acl_queries_and_no_per_item_query(session):
    tids = list(range(1000, 1501))
    session.execute(text("INSERT INTO pre_forum_thread "
        "(tid,fid,sortid,author,authorid,subject,digest,recommends,heats,views,displayorder) "
        "VALUES (:tid,46,1,'synthetic',1,'synthetic',0,0,0,0,0)"),
        [{'tid': tid} for tid in tids])
    session.commit()
    queries = []
    def track(*args):
        queries.append(args[2])
    event.listen(session.bind, 'before_cursor_execute', track)
    try:
        result = read_rating_snapshot(session, tids)
        assert len(queries) == 8  # ceil(501/100) + forum metadata + guest group.
        assert set(result) == set(tids)
        assert result[1500] == {'score': None, 'rating_count': 0}
        assert 5 not in result and 6 not in result and 7 not in result
        queries.clear()
        assert read_rating_snapshot(session, []) == {}
        assert not queries
        assert read_rating_snapshot(session, [1] * 501)[1]['rating_count'] == 0
        assert len(queries) == 3
        with pytest.raises(ValueError):
            read_ratings(session, list(range(1, 102)))  # Public cap unchanged.
    finally:
        event.remove(session.bind, 'before_cursor_execute', track)


@pytest.mark.parametrize('data', [
    {'score': 0, 'count': 9}, {'score': None, 'count': 10},
    {'score': 6, 'count': 10}, {'score': -1, 'count': 10},
    {'score': math.nan, 'count': 10}, {'score': math.inf, 'count': 10},
    {'score': None, 'count': -1}, {'score': None, 'count': True},
    {'score': None, 'count': '9'}, {'score': '4.47', 'count': 10},
    {'score': 4.47, 'count': 10, 'uid': 1},
])
def test_nested_model_rejects_invalid_public_contract(data):
    with pytest.raises(ValidationError):
        ModRating.model_validate(data)


def test_openapi_lists_only_new_mod_rating_fields_and_preserves_live_contract():
    schemas = main.app.openapi()['components']['schemas']
    assert not {'recommend_weight', 'heats'} & schemas['ThreadMeta']['properties'].keys()
    assert {'views', 'featured_level'} <= schemas['ThreadMeta']['properties'].keys()
    assert set(schemas['ModRating']['properties']) == {'score', 'count'}
    assert set(schemas['ModRating']['required']) == {'score', 'count'}
    assert set(schemas['RatingSummary']['properties']) == {'score', 'rating_count'}
    for name in ['ModInfoOriginal', 'ModInfoTranslated', 'ModInfoReposted']:
        assert 'mod_rating' in schemas[name]['properties']
        assert 'mod_recommendation_score' in schemas[name]['properties']
    assert 'mod_rating' not in schemas['GameInfo']['properties']
