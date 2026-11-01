import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session
from api import router
from db import get_session
from ratings import read_ratings, RatingUnavailable


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    with engine.begin() as connection:
        for ddl in [
            "CREATE TABLE pre_forum_thread(tid INTEGER PRIMARY KEY, fid INTEGER DEFAULT 46, sortid INTEGER DEFAULT 1, displayorder INTEGER DEFAULT 0, readperm INTEGER DEFAULT 0, price INTEGER DEFAULT 0, special INTEGER DEFAULT 0, recommend_add INTEGER DEFAULT 0, recommend_sub INTEGER DEFAULT 0)",
            "CREATE TABLE pre_forum_modrating_summary(tid INTEGER PRIMARY KEY, rating_count INTEGER, display_score NUMERIC, algorithm_version INTEGER DEFAULT 2)",
            "CREATE TABLE pre_forum_forum(fid INTEGER PRIMARY KEY, fup INTEGER, type TEXT, status INTEGER DEFAULT 1)",
            "CREATE TABLE pre_forum_forumfield(fid INTEGER PRIMARY KEY, password TEXT DEFAULT '', viewperm TEXT DEFAULT '', formulaperm TEXT DEFAULT '', price INTEGER DEFAULT 0)",
            "CREATE TABLE pre_common_usergroup_field(groupid INTEGER PRIMARY KEY, readaccess INTEGER)",
            "INSERT INTO pre_common_usergroup_field VALUES(7,10)",
            "INSERT INTO pre_forum_forum VALUES(1,0,'group',1),(46,1,'forum',1),(71,46,'sub',1)",
            "INSERT INTO pre_forum_forumfield(fid) VALUES(1),(46),(71)",
            "INSERT INTO pre_forum_thread(tid) VALUES(100),(101),(102),(103)",
            "INSERT INTO pre_forum_modrating_summary VALUES(100,10,0,2),(101,9,NULL,2),(102,20,4.47,2)",
        ]:
            connection.execute(text(ddl))
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_backend_persisted_only_and_missing_new_thread(db):
    assert read_ratings(db, [100, 101, 102, 103]) == {
        100: {'score': 0.0, 'rating_count': 10}, 101: {'score': None, 'rating_count': 9},
        102: {'score': 4.47, 'rating_count': 20}, 103: {'score': None, 'rating_count': 0}}


@pytest.mark.parametrize('sql', [
    'UPDATE pre_forum_thread SET displayorder=-2',
    'UPDATE pre_forum_thread SET sortid=9',
    'UPDATE pre_forum_thread SET fid=99',
    'UPDATE pre_forum_thread SET readperm=20',
    'UPDATE pre_forum_thread SET price=1',
    'UPDATE pre_forum_forum SET status=0 WHERE fid=46',
    'UPDATE pre_forum_forum SET status=3 WHERE fid=46',
    "UPDATE pre_forum_forumfield SET password='protected' WHERE fid=46",
    "UPDATE pre_forum_forumfield SET viewperm='10' WHERE fid=46",
    "UPDATE pre_forum_forumfield SET formulaperm='formula' WHERE fid=46",
    'UPDATE pre_forum_forumfield SET price=1 WHERE fid=46',
    "UPDATE pre_forum_forumfield SET viewperm='10' WHERE fid=1",
    "DELETE FROM pre_forum_forumfield WHERE fid=1",
    'UPDATE pre_forum_forum SET fup=46 WHERE fid=1',
    'UPDATE pre_common_usergroup_field SET readaccess=0',
])
def test_guest_acl_thread_forum_and_parent(db, sql):
    db.execute(text(sql))
    assert read_ratings(db, [100]) == {}


def test_subforum_modding_and_explicit_guest_group(db):
    db.execute(text('UPDATE pre_forum_thread SET fid=71,sortid=3'))
    db.execute(text("UPDATE pre_forum_forumfield SET viewperm='7' WHERE fid=71"))
    assert read_ratings(db, [100])[100]['score'] == 0
    db.execute(text("UPDATE pre_forum_forumfield SET viewperm='17' WHERE fid=71"))
    assert read_ratings(db, [100]) == {}


@pytest.mark.parametrize('sql', [
    'UPDATE pre_forum_modrating_summary SET algorithm_version=1',
    'UPDATE pre_forum_modrating_summary SET algorithm_version=3',
    'UPDATE pre_forum_modrating_summary SET display_score=6',
    'UPDATE pre_forum_modrating_summary SET display_score=NULL WHERE tid=100',
    'UPDATE pre_forum_modrating_summary SET rating_count=-1',
    'UPDATE pre_forum_thread SET recommend_add=1 WHERE tid=103',
])
def test_invalid_or_unmigrated_result_is_not_zero(db, sql):
    db.execute(text(sql))
    with pytest.raises(RatingUnavailable):
        read_ratings(db, [100, 103])


def test_bounded_query_count(db):
    statements = []
    def track(*args):
        statements.append(args[2])
    event.listen(db.bind, 'before_cursor_execute', track)
    try:
        read_ratings(db, list(range(1, 101)))
        assert len(statements) == 3
    finally:
        event.remove(db.bind, 'before_cursor_execute', track)


def test_routes_contract_permissions_and_unavailable(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        response = client.get('/mods/100/rating')
        assert response.json() == {'score': 0.0, 'rating_count': 10}
        assert response.headers['cache-control'] == 'no-store'
        response = client.get('/mods/ratings?tid=100&tid=101&tid=999')
        assert response.json() == {'100': {'score': 0.0, 'rating_count': 10}, '101': {'score': None, 'rating_count': 9}}
        assert client.get('/mods/0/rating').status_code == 422
        assert client.get('/mods/ratings?tid=0').status_code == 422
        assert client.get('/mods/ratings?' + '&'.join('tid=1' for _ in range(101))).status_code == 422
        assert client.get('/mods/ratings').status_code == 422
        db.execute(text('UPDATE pre_forum_thread SET displayorder=-1 WHERE tid=100'))
        assert client.get('/mods/100/rating').status_code == 404
        db.execute(text('DROP TABLE pre_forum_modrating_summary'))
        response = client.get('/mods/101/rating')
        assert response.status_code == 503 and 'score' not in response.json()


def test_v2_reads_compressed_count_and_php_score_without_recomputing(db):
    db.execute(text('UPDATE pre_forum_thread SET recommend_add=303,recommend_sub=6 WHERE tid=102'))
    db.execute(text('UPDATE pre_forum_modrating_summary SET rating_count=21,display_score=4.14 WHERE tid=102'))
    assert read_ratings(db, [102]) == {102: {'score': 4.14, 'rating_count': 21}}


# PHP serialize(array('', '', 'message'=>'', 'medal'=>NULL, 'users'=>'')),
# observed on production public boards; no formula/user/medal restriction exists.
EMPTY_NATIVE_FORMULA = 'a:5:{i:0;s:0:"";i:1;s:0:"";s:7:"message";s:0:"";s:5:"medal";N;s:5:"users";s:0:"";}'


@pytest.mark.parametrize('fid', [1, 46, 71])
def test_canonical_empty_formula_on_public_forum_and_ancestors(db, fid):
    db.execute(text('UPDATE pre_forum_thread SET fid=71'))
    db.execute(text('UPDATE pre_forum_forumfield SET formulaperm=:rule WHERE fid=:fid'),
               {'rule': EMPTY_NATIVE_FORMULA, 'fid': fid})
    assert read_ratings(db, [100, 101]) == {
        100: {'score': 0.0, 'rating_count': 10}, 101: {'score': None, 'rating_count': 9}}


@pytest.mark.parametrize('rule', [
    EMPTY_NATIVE_FORMULA.replace('i:0;s:0:"";', 'i:0;s:1:"x";'),
    EMPTY_NATIVE_FORMULA.replace('i:1;s:0:"";', 'i:1;s:1:"1";'),
    EMPTY_NATIVE_FORMULA.replace('s:7:"message";s:0:"";', 's:7:"message";s:1:"x";'),
    EMPTY_NATIVE_FORMULA.replace('s:5:"medal";N;', 's:5:"medal";a:1:{i:0;i:1;}'),
    EMPTY_NATIVE_FORMULA.replace('s:5:"users";s:0:"";', 's:5:"users";s:1:"x";'),
    EMPTY_NATIVE_FORMULA.replace('a:5:', 'a:6:'),
    EMPTY_NATIVE_FORMULA[:-1],
    ' ' + EMPTY_NATIVE_FORMULA,
    EMPTY_NATIVE_FORMULA + ' ',
    'O:8:"stdClass":0:{}',
    'a:0:{}',
    '{"formula":""}',
])
@pytest.mark.parametrize('fid', [1, 46])
def test_nonempty_unknown_or_malformed_formula_stays_private(db, fid, rule):
    db.execute(text('UPDATE pre_forum_forumfield SET formulaperm=:rule WHERE fid=:fid'),
               {'rule': rule, 'fid': fid})
    assert read_ratings(db, [100]) == {}


def test_routes_accept_only_canonical_empty_formula_without_changing_contract(db):
    db.execute(text('UPDATE pre_forum_forumfield SET formulaperm=:rule'),
               {'rule': EMPTY_NATIVE_FORMULA})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        response = client.get('/mods/100/rating')
        assert response.status_code == 200
        assert response.json() == {'score': 0.0, 'rating_count': 10}
        assert response.headers['cache-control'] == 'no-store'
        response = client.get('/mods/ratings?tid=100&tid=101')
        assert response.json() == {'100': {'score': 0.0, 'rating_count': 10},
                                   '101': {'score': None, 'rating_count': 9}}
        db.execute(text("UPDATE pre_forum_forumfield SET formulaperm='formula' WHERE fid=1"))
        assert client.get('/mods/100/rating').status_code == 404
