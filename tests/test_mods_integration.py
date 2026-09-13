import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from phpserialize import dumps
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import main
from cache import mod_cache
from dao import ModDAO
from tables import ForumThread, ForumTypeOption, ForumTypeOptionVar
from tables import ForumAttachment
from models import ModRelease
from sqlalchemy import event
from sqlalchemy.exc import OperationalError


def rules(choices):
    return dumps({'choices': choices}).decode('utf-8')


@pytest.fixture
def session():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        definitions = {
            9: ('modVersion', rules('modVersion_098x=0.98')),
            13: ('modSafeRm', rules('1=是\r\n2=否')),
            19: ('modDependency', rules('1=其它')),
            12: ('modType', rules('utility=工具')),
            29: ('modLanguage', rules('zh=中文')),
            39: ('modReleaseFilesMapping', ''),
            42: ('modAllowDirectDownload', rules('1=是\r\n2=否')),
        }
        fields = {'modID': 'example', 'modName_cn': '测试', 'modName_en': 'Test',
                  'modReleaseVersion': 'legacy version', 'modShortDes': 'description',
                  'modUpdateDate': '2026-09-12'}
        for i, (identifier, _) in enumerate(fields.items(), 100):
            definitions[i] = (identifier, '')
        session.add_all([ForumTypeOption(optionid=i, identifier=name, title=name, type='text', rules=r)
                         for i, (name, r) in definitions.items()])
        # Include all three model variants and every existing SQL exclusion.
        cases = [(46, 1, 0), (60, 2, 0), (78, 3, 0), (71, 1, 0),
                 (99, 1, 0), (46, 1, -1), (46, 0, 0)]
        for tid, (fid, sortid, displayorder) in enumerate(cases, 1):
            session.add(ForumThread(tid=tid, fid=fid, sortid=sortid, author='author',
                                    authorid=1, subject='test', digest=0, recommends=0, heats=28, views=1000,
                                    displayorder=displayorder))
            values = {**fields, 'modType': 'utility', 'modVersion': 'modVersion_098x',
                      'modSafeRm': '1', 'modLanguage': 'zh'}
            if tid != 2:
                values['modReleaseFilesMapping'] = 'broken' if tid == 3 else json.dumps([
                    {'aid': 123, 'gameVersion': 'modVersion_098x', 'modVersion': '1.2'},
                    {'aid': 456, 'gameVersion': 'invalid', 'modVersion': '1.2'},
                ])
                values['modAllowDirectDownload'] = '1' if tid == 1 else '2'
            for optionid, (name, _) in definitions.items():
                if name in values:
                    session.add(ForumTypeOptionVar(sortid=sortid, tid=tid, fid=fid,
                                                  optionid=optionid, expiration=0, value=values[name]))
        session.commit()
        yield session
    engine.dispose()


def test_dao_models_and_existing_filters(session):
    mods = ModDAO(session).get_all_mods()
    assert [m.thread_meta.tid for m in mods] == [1, 2, 3, 4]
    assert [m.mod_info_type.value for m in mods] == ['original', 'reposted', 'translated', 'original']
    assert all(m.mod_version == 'legacy version' for m in mods)
    assert [m.mod_allow_direct_download for m in mods] == [True, False, False, False]
    assert [r.attachment_id for r in mods[0].mod_releases] == [123]
    assert mods[1].mod_releases is None
    assert mods[2].mod_releases is None


@pytest.mark.parametrize('value', ['', '0', '2', 'true', 'yes', 'unknown', '1'])
def test_direct_download_choices(session, value):
    option = session.get(ForumTypeOptionVar, (1, 1, 46, 42))
    option.value = value
    session.commit()
    assert ModDAO(session).get_all_mods()[0].mod_allow_direct_download is (value == '1')


@pytest.mark.parametrize('value', ['', 'broken', 'a:0:{}'])
def test_invalid_choices_fail_closed(session, value):
    option = session.get(ForumTypeOption, 42)
    option.rules = value
    session.commit()
    assert ModDAO(session).get_all_mods()[0].mod_allow_direct_download is False


def test_route_both_caches_and_refresh(session, monkeypatch):
    monkeypatch.setattr(main, 'refresh_cache', lambda: mod_cache.refresh(session))
    FastAPICache.reset()
    try:
        with TestClient(main.app) as client:
            client.portal.call(FastAPICache.clear)
            first = client.get('/mods')
            assert first.status_code == 200
            assert first.headers['x-fastapi-cache'] == 'MISS'
            data = first.json()
            assert client.get('/mods').json() == data
            assert [m['thread_meta']['fid'] for m in data] == [46, 60, 78]
            assert data[0]['mod_releases'][0]['game_version'] == '0.98'
            assert data[0]['mod_releases'][0]['download_count'] is None
            assert data[0]['thread_meta']['heats'] == 28
            assert data[0]['thread_meta']['views'] == 1000
            assert data[1]['mod_releases'] is None
            assert data[1]['mod_allow_direct_download'] is False
            hit = client.get('/mods')
            assert hit.headers['x-fastapi-cache'] == 'HIT'
            # Existing union decoding drops an empty mod_translator_names on HIT.
            # Normalize only that known empty/missing difference.
            def comparable(items):
                return [{'mod_translator_names': [], **item} for item in items]
            assert comparable(hit.json()) == comparable(data)
            all_mods = client.get('/mods?include_modding=true')
            assert [m['thread_meta']['fid'] for m in all_mods.json()] == [46, 60, 78, 71]
            assert client.get('/mods?include_modding=true').headers['x-fastapi-cache'] == 'HIT'
            assert comparable(client.get('/mods?include_modding=false').json()) == comparable(data)
            assert client.get('/status').json()['cache']['status'] == 'ok'
            # Exercise the real refresh function and its response-cache invalidation.
            option = session.get(ForumTypeOptionVar, (1, 1, 46, 39))
            option.value = '[]'
            session.commit()
            with monkeypatch.context() as patch:
                patch.setattr(mod_cache, 'refresh', lambda: mod_cache.__class__.refresh(mod_cache, session))
                # The startup monkeypatch above is removed only for this call.
                patch.setattr(main, 'refresh_cache', ORIGINAL_REFRESH)
                main.refresh_cache()
                client.portal.call(asyncio.sleep, 0)
            refreshed = client.get('/mods')
            assert refreshed.headers['x-fastapi-cache'] == 'MISS'
            assert refreshed.json()[0]['mod_releases'] == []
    finally:
        FastAPICache.reset()


ORIGINAL_REFRESH = main.refresh_cache


@pytest.mark.parametrize('translators', ['', '译者甲,译者乙'])
def test_translators_survive_response_cache(session, monkeypatch, translators):
    session.add(ForumTypeOption(optionid=999, identifier='modTranslator', title='译者', type='text', rules=''))
    session.add(ForumTypeOptionVar(sortid=3, tid=3, fid=78, optionid=999, expiration=0, value=translators))
    session.commit()
    monkeypatch.setattr(main, 'refresh_cache', lambda: mod_cache.refresh(session))
    FastAPICache.reset()
    try:
        with TestClient(main.app) as client:
            client.portal.call(FastAPICache.clear)
            first = client.get('/mods')
            second = client.get('/mods')
            assert first.headers['x-fastapi-cache'] == 'MISS'
            assert second.headers['x-fastapi-cache'] == 'HIT'
            assert first.json() == second.json()
            translated = next(m for m in second.json() if m['thread_meta']['tid'] == 3)
            assert translated['mod_translator_names'] == (sorted(translators.split(',')) if translators else [])
    finally:
        FastAPICache.reset()


def test_download_counts_skip_invalid_without_losing_valid(session):
    session.add_all([ForumAttachment(aid=123, tid=1, downloads=620),
                     ForumAttachment(aid=124, tid=1, downloads=0),
                     ForumAttachment(aid=125, tid=999, downloads=900),
                     ForumAttachment(aid=126, tid=1, downloads=-1)])
    option = session.get(ForumTypeOptionVar, (1, 1, 46, 39))
    option.value = json.dumps([{'aid': aid, 'gameVersion': 'modVersion_098x', 'modVersion': '1'}
                               for aid in [123, 124, 125, 126, 127, 123]])
    session.commit()
    mods = ModDAO(session).get_all_mods()
    assert [r.download_count for r in mods[0].mod_releases] == [620, 0, None, None, None, 620]
    # 另一个帖子的同一附件映射不能借用本帖计数。
    assert mods[3].mod_releases[0].download_count is None
    session.delete(session.get(ForumAttachment, 123))
    session.commit()
    assert [r.download_count for r in ModDAO(session).get_all_mods()[0].mod_releases] == [None, 0, None, None, None, None]


def test_attachment_queries_are_batched_and_deduplicated(session):
    mod = ModDAO(session).get_all_mods()[0]
    mod.mod_releases = [ModRelease(attachment_id=aid, game_version_id='v', game_version='0.98', mod_version='1')
                        for aid in range(1, 502)]
    mod.mod_releases += [mod.mod_releases[0]] * 10
    queries = []
    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append((statement, parameters))
    event.listen(session.bind, 'before_cursor_execute', record)
    try:
        ModDAO(session).populate_download_counts([mod])
        assert len(queries) == 2
        assert [len(params) for _, params in queries] == [500, 1]
        assert all('pre_forum_attachment' in sql for sql, _ in queries)
        queries.clear()
        mod.mod_releases = []
        ModDAO(session).populate_download_counts([mod])
        mod.mod_releases = None
        ModDAO(session).populate_download_counts([mod])
        assert queries == []
    finally:
        event.remove(session.bind, 'before_cursor_execute', record)


def test_failed_attachment_refresh_preserves_snapshot(session, monkeypatch):
    from cache import ModCache
    import cache
    snapshot = ModCache()
    assert snapshot.refresh(session)
    previous = snapshot.get_all_mods()
    previous_time = snapshot.get_update_time()
    original_exec = session.exec
    def fail_attachment(statement, *args, **kwargs):
        if 'pre_forum_attachment' in str(statement):
            raise OperationalError('attachment query', {}, Exception('unavailable'))
        return original_exec(statement, *args, **kwargs)
    monkeypatch.setattr(session, 'exec', fail_attachment)
    monkeypatch.setattr(cache.time, 'sleep', lambda _: None)
    assert snapshot.refresh(session) is False
    assert snapshot.get_all_mods() is previous
    assert snapshot.get_update_time() == previous_time


def test_new_statistics_cached_without_request_sql(session, monkeypatch):
    session.add(ForumAttachment(aid=123, tid=1, downloads=42))
    session.commit()
    monkeypatch.setattr(main, 'refresh_cache', lambda: mod_cache.refresh(session))
    FastAPICache.reset()
    try:
        with TestClient(main.app) as client:
            client.portal.call(FastAPICache.clear)
            def reject_query(*args, **kwargs):
                raise AssertionError('访客请求不应访问数据库')
            with monkeypatch.context() as patch:
                patch.setattr(session, 'exec', reject_query)
                for _ in range(2):
                    result = client.get('/mods').json()[0]
                    assert result['mod_releases'][0]['download_count'] == 42
                    assert result['thread_meta']['heats'] == 28
                    assert result['thread_meta']['views'] == 1000
            attachment = session.get(ForumAttachment, 123)
            attachment.downloads = 50
            session.add(attachment)
            session.commit()
            assert mod_cache.refresh(session)
            client.portal.call(FastAPICache.clear)
            assert client.get('/mods').json()[0]['mod_releases'][0]['download_count'] == 50
            schema = client.get('/openapi.json').json()['components']['schemas']
            assert {'heats', 'views'} <= schema['ThreadMeta']['properties'].keys()
            assert 'download_count' in schema['ModRelease']['properties']
    finally:
        FastAPICache.reset()
