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
                                    authorid=1, subject='test', digest=0, recommends=0,
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
            first = client.get('/mods')
            assert first.status_code == 200
            assert first.headers['x-fastapi-cache'] == 'MISS'
            data = first.json()
            assert [m['thread_meta']['fid'] for m in data] == [46, 60, 78]
            assert data[0]['mod_releases'][0]['game_version'] == '0.98'
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
