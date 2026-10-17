import asyncio
import html
import json

import pytest
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

import main
import cache
from cache import GameCache, game_cache, mod_cache
from game_releases import GameDAO, parse_game_releases, STARSECTOR_AUTHOR_NAMES
from tables import ForumThread, ForumTypeOption, ForumTypeOptionVar, ForumAttachment, ATTACHMENT_DETAILS
from test_mods_integration import session, rules

ENTRY = dict(aid=900, isFullGame=True, gameVersion='0.98', platform='windows',
             language='zh-Hans', packageType='zip', releaseVersion='v2026.10.15',
             displayName='中文汉化版(宋体版) v2026.10.15')


@pytest.fixture
def games(session):
    # Deliberately use different field IDs: lookup must follow identifiers.
    for oid, identifier, definition in [(144,'gameReleaseInfoMapping',''),
            (145,'gameAllowDirectDownload',rules('allow=是\r\ndeny=否')),
            (146,'gameReleaseAuthor',''), (147,'gameReleaseName',''),
            (148,'gameReleaseVersion','')]:
        session.add(ForumTypeOption(optionid=oid, identifier=identifier, title=identifier,
                                   type='text', rules=definition))
    for tid, fid, sortid, order in [(20,39,9,3),(21,39,9,-1),(22,99,9,0),(23,39,1,0)]:
        session.add(ForumThread(tid=tid, fid=fid, sortid=sortid, displayorder=order,
            subject='游戏 (中文) "测试"', author='author', authorid=3,
            digest=3, recommends=5, heats=9, views=100))
        for oid, value in [(144,html.escape(json.dumps([ENTRY, {**ENTRY,'aid':901,'isFullGame':False,
                'packageType':'self_extracting','displayName':' '}]))),
                (145,'allow'),(146,'作者乙, 作者甲,作者乙, ' ),
                (147,'汉化版 (测试)'),(148,'v2026.10.15-master')]:
            session.add(ForumTypeOptionVar(sortid=sortid, tid=tid, fid=fid,
                optionid=oid, expiration=0, value=value))
    session.add_all([ForumAttachment(aid=900,tid=20,downloads=10,tableid=7),
                     ForumAttachment(aid=901,tid=20,downloads=0,tableid=2)])
    for aid, shard in [(900,7),(901,2)]:
        session.execute(ATTACHMENT_DETAILS[shard].insert(),dict(aid=aid,tid=20,
            filename='游戏 (中文) "测试" &quot;.zip',filesize=195,isimage=0,dateline=1792121804))
    session.commit()
    return session


@pytest.mark.parametrize('value',[None,'','  ','null','{}','oops','[','"text"',42])
def test_invalid_array(value):
    assert parse_game_releases(value,20) is None


@pytest.mark.parametrize('escaped',[False,True])
def test_literal_entities_order_and_null(escaped):
    entries=[{**ENTRY,'displayName':'字面 &quot; &copy; "引号"'},
             {**ENTRY,'aid':901,'isFullGame':False,'platform':'universal','displayName':' '}]
    raw=json.dumps(entries)
    result=parse_game_releases(html.escape(raw) if escaped else raw,20)
    assert [r.attachment_id for r in result]==[900,901]
    assert result[0].display_name==entries[0]['displayName']
    assert result[1].display_name is None
    assert result[1].is_full_game is False
    assert result[0].release_version=='v2026.10.15'


@pytest.mark.parametrize('patch',[
    {'aid':True},{'aid':1.5},{'aid':0},{'aid':4294967296},{'aid':'９'},
    {'isFullGame':'false'},{'isFullGame':1},{'gameVersion':''},{'gameVersion':'x'*65},
    {'releaseVersion':False},{'releaseVersion':'x'*129},{'platform':'Windows'},
    {'language':'中文'},{'language':'zh'},{'packageType':'exe'},{'displayName':{}},
    {'displayName':'x'*201},{'displayName':'\ud800'},{'extra':'bad'},
])
def test_bad_item_is_local(patch,caplog):
    result=parse_game_releases(json.dumps([{**ENTRY,**patch},ENTRY]),20)
    assert len(result)==1
    assert result[0].attachment_id==900
    assert '20' in caplog.text


def test_limits_and_duplicates():
    assert parse_game_releases('[]',20)==[]
    assert parse_game_releases(json.dumps([ENTRY,ENTRY]),20)[0].attachment_id==900
    assert len(parse_game_releases(json.dumps([ENTRY,ENTRY]),20))==1
    assert parse_game_releases(json.dumps([ENTRY]*201),20) is None


def test_game_dao_contract_and_filters(games):
    result=GameDAO(games).get_all_games()
    assert len(result)==1
    game=result[0]
    assert game.thread_meta.tid==20
    assert game.thread_meta.title=='游戏 (中文) "测试"'
    assert game.game_author_names==[*STARSECTOR_AUTHOR_NAMES, '作者乙','作者甲']
    assert game.game_release_name=='汉化版 (测试)'
    assert game.game_release_version=='v2026.10.15-master'
    assert game.game_publish_urls==['https://www.fossic.org/thread-20-1-1.html']
    assert game.game_allow_direct_download is True
    assert len(game.game_releases)==2
    a,b=game.game_releases
    assert a.file_name=='游戏 (中文) "测试" &quot;.zip'
    assert a.file_size==195 and a.uploaded_at==1792121804
    assert a.download_url.endswith('action=gamedownload&aid=900')
    assert b.download_count==0 and b.display_name is None
    assert game.model_dump(mode='json')['thread_meta']['featured_level']==3


@pytest.mark.parametrize('value',['','0','deny','true','unknown','allow'])
def test_switch_fail_closed(games,value):
    option=games.get(ForumTypeOptionVar,(9,20,39,145));option.value=value;games.commit()
    game=GameDAO(games).get_all_games()[0]
    assert game.game_allow_direct_download is (value=='allow')
    assert (game.game_releases[0].download_url is not None) is (value=='allow')


def test_missing_author_and_switch(games):
    for oid in [145,146]:games.delete(games.get(ForumTypeOptionVar,(9,20,39,oid)))
    games.commit()
    game=GameDAO(games).get_all_games()[0]
    assert game.game_author_names==list(STARSECTOR_AUTHOR_NAMES) and not game.game_allow_direct_download
    assert all(r.download_url is None for r in game.game_releases)


@pytest.mark.parametrize('definition',['','broken','a:0:{}'])
def test_invalid_choices(games,definition):
    option=games.get(ForumTypeOption,145);option.rules=definition;games.commit()
    assert not GameDAO(games).get_all_games()[0].game_allow_direct_download


@pytest.mark.parametrize('kind',['missing','cross_index','cross_detail','image','negative_size'])
def test_invalid_attachment_metadata(games,kind):
    if kind=='missing':games.delete(games.get(ForumAttachment,900))
    elif kind=='cross_index':games.get(ForumAttachment,900).tid=999
    else:
        table=ATTACHMENT_DETAILS[7]
        patch={'tid':999} if kind=='cross_detail' else {'isimage':1} if kind=='image' else {'filesize':-1}
        games.execute(table.update().where(table.c.aid==900).values(**patch))
    games.commit()
    releases=GameDAO(games).get_all_games()[0].game_releases
    assert releases[0].file_name is None and releases[0].download_url is None
    assert releases[1].file_size==195


def test_failure_keeps_game_snapshot_and_mods_refresh(games,monkeypatch):
    snapshot=GameCache();assert snapshot.refresh(games)
    previous=snapshot.get_all_games();timestamp=snapshot.get_update_time()
    def failure(_):raise OperationalError('query',{},Exception('unavailable'))
    monkeypatch.setattr(snapshot,'_fetch',failure)
    monkeypatch.setattr(cache.time,'sleep',lambda _:None)
    assert not snapshot.refresh(games)
    assert snapshot.get_all_games() is previous and snapshot.get_update_time()==timestamp
    calls=[]
    monkeypatch.setattr(mod_cache,'refresh',lambda:calls.append('mod') or True)
    monkeypatch.setattr(game_cache,'refresh',lambda:calls.append('game') or False)
    monkeypatch.setattr(main,'_loop',None)
    main.refresh_cache()
    assert calls==['mod','game']


def test_game_endpoint_caches_schema_and_invalidation(games,monkeypatch):
    monkeypatch.setattr(main,'refresh_cache',lambda:(mod_cache.refresh(games),game_cache.refresh(games)))
    FastAPICache.reset()
    try:
        with TestClient(main.app) as client:
            client.portal.call(FastAPICache.clear)
            first=client.get('/games');second=client.get('/games')
            assert first.status_code==200
            assert first.headers['x-fastapi-cache']=='MISS'
            assert second.headers['x-fastapi-cache']=='HIT'
            assert first.json()==second.json()
            assert len(first.json()[0]['game_releases'])==2
            assert 'game_title' not in first.json()[0]
            assert first.json()[0]['game_release_name']=='汉化版 (测试)'
            assert first.json()[0]['game_release_version']=='v2026.10.15-master'
            assert first.json()[0]['thread_meta']['title']=='游戏 (中文) "测试"'
            mods=client.get('/mods').json()
            assert mods and all('title' in mod['thread_meta'] for mod in mods)
            queries=[]
            def record(*args):queries.append(args)
            event.listen(games.bind,'before_cursor_execute',record)
            try:
                assert client.get('/games').json()==first.json()
                assert not queries
            finally:event.remove(games.bind,'before_cursor_execute',record)
            assert client.get('/status').json()['game_cache']['game_count']==1
            schema=client.get('/openapi.json').json()
            assert '/games' in schema['paths']
            assert 'title' in schema['components']['schemas']['ThreadMeta']['required']
            props=schema['components']['schemas']['GameInfo']['properties']
            assert 'game_title' not in props
            assert 'game_release_name' in props and 'game_release_version' in props
            assert 'game_releases' in schema['components']['schemas']['GameInfo']['properties']
            assert schema['components']['schemas']['GameRelease']['properties']['platform']['enum']==['windows','macos','linux','universal']
            games.get(ForumTypeOptionVar,(9,20,39,145)).value='deny';games.commit()
            assert game_cache.refresh(games)
            client.portal.call(FastAPICache.clear)
            updated=client.get('/games')
            assert updated.headers['x-fastapi-cache']=='MISS'
            assert not updated.json()[0]['game_allow_direct_download']
            assert updated.json()[0]['game_releases'][0]['download_url'] is None
    finally:FastAPICache.reset()


@pytest.mark.parametrize('language',['zh-Hans','zh-Hant','en','other'])
def test_game_language_values(language):
    result=parse_game_releases(json.dumps([{**ENTRY,'language':language}]),20)
    assert len(result)==1 and result[0].language==language

@pytest.mark.parametrize('value', ['', '  ', 'Alex Mosolov, Alex Mosolov, 远星汉化组,远星汉化组, '])
def test_author_union(games, value):
    games.get(ForumTypeOptionVar,(9,20,39,146)).value=value
    games.commit()
    expected=list(STARSECTOR_AUTHOR_NAMES)
    if value.strip():
        expected.append('远星汉化组')
    assert GameDAO(games).get_all_games()[0].game_author_names==expected


@pytest.mark.parametrize('value', [None, '', '  '])
def test_optional_release_fields(games, value):
    for oid in [147,148]:
        row=games.get(ForumTypeOptionVar,(9,20,39,oid))
        if value is None:
            games.delete(row)
        else:
            row.value=value
    games.commit()
    game=GameDAO(games).get_all_games()[0]
    assert game.game_release_name is None and game.game_release_version is None
    assert game.thread_meta.title=='游戏 (中文) "测试"'
    assert game.game_releases[0].game_version=='0.98'
    assert game.game_releases[0].release_version=='v2026.10.15'
