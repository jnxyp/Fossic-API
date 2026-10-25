import html
import itertools
import json

import pytest
from fastapi.testclient import TestClient
from phpserialize import dumps
from pydantic import ValidationError
from sqlalchemy import event

import cache
import dao
import main
from cache import snapshot_cache
from mod_ai_declaration import MAX_BYTES, is_public_ai_option, parse_mod_ai_declaration
from models import ModAiDeclaration
from tables import ForumThread, ForumTypeOption, ForumTypeOptionVar
from test_mods_integration import session

DIMENSIONS = ('code', 'art', 'audio', 'text')
UNKNOWN = dict.fromkeys(('status', *DIMENSIONS), 'undeclared')


def source(status='no', **changes):
    return {'status': status, **dict.fromkeys(DIMENSIONS, 'none'), **changes}


def test_source_undeclared_normalizes_after_validation():
    assert parse_mod_ai_declaration(json.dumps(source('undeclared')), 1).model_dump() == UNKNOWN
    assert parse_mod_ai_declaration(json.dumps(source('undeclared', code='full')), 1).model_dump() == UNKNOWN
    assert parse_mod_ai_declaration(json.dumps(source('no')), 1).model_dump() == source('no')


@pytest.mark.parametrize('dimensions', list(itertools.product(['none', 'assisted', 'full'], repeat=4)))
def test_all_source_yes_dimension_combinations(dimensions):
    data = source('yes', **dict(zip(DIMENSIONS, dimensions)))
    expected = data if any(value != 'none' for value in dimensions) else UNKNOWN
    assert parse_mod_ai_declaration(json.dumps(data), 1).model_dump() == expected


@pytest.mark.parametrize('raw', [None, '', '  \n\t', 'null', '[]', '{}', 'true', '1',
    '{broken', 123, [], json.dumps({'status': 'no'}),
    json.dumps(source('unknown')), json.dumps(source('yes')),
    json.dumps(source('no', art='assisted')), json.dumps(source('no', text='undeclared')),
    json.dumps(source('undeclared', code='full')), json.dumps(source('no', extra='secret')),
    json.dumps(source('no', code=0)), json.dumps(source('no', art=None)),
    json.dumps(source('no', audio=True)), json.dumps(source('yes', code=['full'])),
    json.dumps(source('yes', code='FULL')), json.dumps(source('yes', text='未使用')),
    '{"status":"yes","status":"no","code":"none","art":"none","audio":"none","text":"none"}',
    '{"status":"no","code":NaN,"art":"none","audio":"none","text":"none"}',
    '[' * 1010 + '0' + ']' * 1010, '\ud800',
])
def test_invalid_or_absent_source_never_claims_non_use(raw):
    assert parse_mod_ai_declaration(raw, 1).model_dump() == UNKNOWN


@pytest.mark.parametrize('dimension', DIMENSIONS)
def test_api_undeclared_values_are_not_valid_forum_storage(dimension, caplog):
    # Invalid source and valid undeclared intentionally share an API fallback;
    # a warning distinguishes rejected data from accepted normalization.
    data = source('undeclared', **{dimension: 'undeclared'})
    assert parse_mod_ai_declaration(json.dumps(data), 1).model_dump() == UNKNOWN
    assert 'modAiDeclaration 无效' in caplog.text


def test_byte_limit_after_one_special_entity_decode(caplog):
    raw = json.dumps(source('yes', code='assisted'))
    boundary = raw + ' ' * (MAX_BYTES - len(raw.encode('utf-8')))
    assert parse_mod_ai_declaration(boundary, 1).status == 'yes'
    escaped = html.escape(boundary, quote=True)
    assert len(escaped) > MAX_BYTES
    assert parse_mod_ai_declaration(escaped, 1).status == 'yes'
    assert parse_mod_ai_declaration(boundary + ' ', 1).model_dump() == UNKNOWN
    assert parse_mod_ai_declaration(html.escape(html.escape(raw, quote=True), quote=True), 1).model_dump() == UNKNOWN
    # UTF-8 byte length, not Unicode character count.
    assert parse_mod_ai_declaration('汉' * 700, 1).model_dump() == UNKNOWN
    assert parse_mod_ai_declaration('x' * (MAX_BYTES * 6 + 1), 1).model_dump() == UNKNOWN


def test_logs_never_include_raw_or_validation_messages(caplog):
    secret = '<script>publisher-private-value</script>'
    assert parse_mod_ai_declaration(json.dumps(source('yes', code=secret)), 765).model_dump() == UNKNOWN
    assert '765' in caplog.text and 'modAiDeclaration' in caplog.text
    assert secret not in caplog.text and 'publisher-private-value' not in caplog.text


@pytest.mark.parametrize('data', [source('undeclared'), source('yes'),
    source('no', code='full'), {**UNKNOWN, 'code': 'none'},
    source('yes', code='full', audio='undeclared'), source('no', extra='x')])
def test_api_model_rejects_inconsistent_or_extra_fields(data):
    with pytest.raises(ValidationError):
        ModAiDeclaration.model_validate(data)


def add_ai(session, tid, raw, *, sortid=None, fid=None, expiration=0):
    # Deliberately not the production optionid: discover by identifier only.
    if session.get(ForumTypeOption, 773) is None:
        session.add(ForumTypeOption(optionid=773, identifier='modAiDeclaration',
            title='AI声明', type='textarea', rules=''))
    thread = session.get(ForumThread, tid)
    session.add(ForumTypeOptionVar(sortid=thread.sortid if sortid is None else sortid,
        tid=tid, fid=thread.fid if fid is None else fid, optionid=773,
        expiration=expiration, value=raw))
    session.commit()


def test_dao_all_types_and_missing_defaults_have_no_extra_queries(session):
    queries = []
    def record(*args):
        queries.append(args[2])
    event.listen(session.bind, 'before_cursor_execute', record)
    try:
        before = dao.ModDAO(session).get_all_mods()
        baseline = len(queries)
        for tid, data in [(1, source('yes', code='assisted')), (2, source('no')),
                          (3, source('undeclared'))]:
            add_ai(session, tid, html.escape(json.dumps(data), quote=True))
        queries.clear()
        after = dao.ModDAO(session).get_all_mods()
        assert len(queries) == baseline
    finally:
        event.remove(session.bind, 'before_cursor_execute', record)
    assert [m.thread_meta.tid for m in before] == [m.thread_meta.tid for m in after]
    for old, new in zip(before, after):
        assert old.model_dump(exclude={'mod_ai_declaration'}) == new.model_dump(exclude={'mod_ai_declaration'})
    assert [m.mod_ai_declaration.status for m in after] == ['yes', 'no', 'undeclared', 'undeclared']
    assert after[2].mod_ai_declaration.model_dump() == UNKNOWN
    assert after[3].mod_ai_declaration.model_dump() == UNKNOWN
    assert after[2].mod_ai_declaration is not after[3].mod_ai_declaration


@pytest.mark.parametrize('protect', ['', dumps({'status':'0','mode':'2','usergroup':'','verify':''}).decode()])
def test_public_option(protect):
    option = ForumTypeOption(optionid=1, title='AI', identifier='modAiDeclaration',
        type='textarea', rules='', protect=protect)
    value = ForumTypeOptionVar(sortid=1, tid=1, fid=46, optionid=1, expiration=0, value='')
    assert is_public_ai_option(option, value, 1000)


@pytest.mark.parametrize('protect', ['bad', 'x' * 4097,
    dumps({'status':'1','usergroup':'','verify':''}).decode(),
    dumps({'status':'0','usergroup':'10','verify':''}).decode(),
    dumps({'status':'0','usergroup':'','verify':'1'}).decode(),
    dumps({}).decode(), dumps({'status':'unknown'}).decode()])
def test_non_public_option_is_not_exposed(session, protect):
    add_ai(session, 1, json.dumps(source('yes', art='full')))
    session.get(ForumTypeOption, 773).protect = protect
    session.commit()
    assert dao.ModDAO(session).get_all_mods()[0].mod_ai_declaration.model_dump() == UNKNOWN


@pytest.mark.parametrize('enabled,expires,visible', [(0,999,True),(1,0,True),
    (1,999,False),(1,1000,False),(1,1001,True)])
def test_native_expiration_switch_and_deadline(session, monkeypatch, enabled, expires, visible):
    add_ai(session, 1, json.dumps(source('yes', art='full')), expiration=expires)
    session.get(ForumTypeOption, 773).expiration = enabled
    session.commit()
    monkeypatch.setattr(dao.time, 'time', lambda: 1000)
    status = dao.ModDAO(session).get_all_mods()[0].mod_ai_declaration.status
    assert status == ('yes' if visible else 'undeclared')


@pytest.mark.parametrize('overrides', [{'sortid':2}, {'fid':60}])
def test_stale_thread_mapping_does_not_override_declaration(session, overrides):
    add_ai(session, 1, json.dumps(source('no')), **overrides)
    assert dao.ModDAO(session).get_all_mods()[0].mod_ai_declaration.model_dump() == UNKNOWN


def test_api_uses_snapshot_and_bad_declaration_does_not_break_statistics(session, monkeypatch):
    monkeypatch.setattr(main, 'refresh_cache', lambda: snapshot_cache.refresh(session))
    monkeypatch.setattr(cache.time, 'time', lambda: 1792931881)
    add_ai(session, 1, json.dumps(source('yes', code='assisted')))
    add_ai(session, 4, json.dumps(source('no')))
    with TestClient(main.app) as client:
        original = client.get('/mods').json()
        assert [m['mod_ai_declaration']['status'] for m in original] == ['yes','undeclared','undeclared']
        raw = session.get(ForumTypeOptionVar, (1,1,46,773))
        raw.value = json.dumps(source('no'))
        session.commit()
        def reject(*args, **kwargs):
            raise AssertionError('Hot request must not query, parse or encode')
        event.listen(session.bind, 'before_cursor_execute', reject)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(dao, 'parse_mod_ai_declaration', reject)
                patch.setattr(cache.TypeAdapter, 'dump_json', reject)
                patch.setattr(snapshot_cache.stats_store, '_connect', reject)
                assert client.get('/mods').json() == original
                all_mods = client.get('/mods?include_modding=true').json()
                assert all_mods[:-1] == original
                assert all_mods[-1]['mod_ai_declaration'] == source('no')
        finally:
            event.remove(session.bind, 'before_cursor_execute', reject)
        assert snapshot_cache.refresh(session)['mods']
        assert client.get('/mods').json()[0]['mod_ai_declaration'] == source('no')
        raw.value = json.dumps(source('no', code='secret'))
        session.commit()
        assert snapshot_cache.refresh(session) == {'mods':True,'games':True}
        updated = client.get('/mods').json()
        assert updated[0]['mod_ai_declaration'] == UNKNOWN
        for old, new in zip(original, updated):
            assert {k:v for k,v in old.items() if k!='mod_ai_declaration'} == {k:v for k,v in new.items() if k!='mod_ai_declaration'}
        assert client.get('/games').json() == []
        schema = client.get('/openapi.json').json()['components']['schemas']
        for name in ['ModInfoOriginal','ModInfoTranslated','ModInfoReposted']:
            assert schema[name]['properties']['mod_ai_declaration']['$ref'].endswith('/ModAiDeclaration')
        fields = schema['ModAiDeclaration']['properties']
        assert fields['status']['enum'] == ['undeclared','yes','no']
        for key in DIMENSIONS:
            assert fields[key]['enum'] == ['undeclared','none','assisted','full']
        assert schema['ModAiDeclaration']['additionalProperties'] is False
        assert 'mod_ai_declaration' not in schema['GameInfo']['properties']
