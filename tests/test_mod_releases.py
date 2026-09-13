import html
import json

import pytest

from mod_releases import parse_mod_releases

VERSIONS = {'modVersion_098x': '0.98'}
ENTRY = {'aid': 12345, 'gameVersion': 'modVersion_098x',
         'gameVersionDisplayValue': 'untrusted', 'modVersion': '1.2.0',
         'modVersionDisplayName': '稳定版 1.2.0'}


@pytest.mark.parametrize('value', [None, '', '  ', 'null', '{}', 'oops', '[', '"text"', 42])
def test_missing_or_invalid(value):
    assert parse_mod_releases(value, VERSIONS, 1) is None


def test_invalid_json_logs_without_raw_content(caplog):
    assert parse_mod_releases('private broken payload', VERSIONS, 77) is None
    assert '77' in caplog.text
    assert 'private broken payload' not in caplog.text


@pytest.mark.parametrize('escaped', [False, True])
def test_order_canonical_names_and_serialization(escaped):
    entries = [ENTRY, {**ENTRY, 'aid': '12346', 'modVersionDisplayName': ' '}, ENTRY]
    value = json.dumps(entries, ensure_ascii=False)
    result = parse_mod_releases(html.escape(value, quote=True) if escaped else value, VERSIONS, 1)
    assert [r.attachment_id for r in result] == [12345, 12346, 12345]
    assert result[0].model_dump() == {
        'attachment_id': 12345, 'game_version_id': 'modVersion_098x',
        'game_version': '0.98', 'mod_version': '1.2.0', 'display_name': '稳定版 1.2.0', 'download_count': None,
    }
    assert result[1].display_name is None
    assert json.loads(result[0].model_dump_json()) == result[0].model_dump()


@pytest.mark.parametrize('patch', [
    {'aid': True}, {'aid': 1.5}, {'aid': 0}, {'aid': -1}, {'aid': '1.0'},
    {'aid': '１２'}, {'aid': None}, {'aid': []}, {'aid': 4294967296},
    {'gameVersion': '9'}, {'gameVersion': []}, {'gameVersion': None},
    {'modVersion': ''}, {'modVersion': ' '}, {'modVersion': 12},
    {'modVersion': '\ud800'}, {'modVersionDisplayName': {}},
])
def test_dirty_entry_is_filtered_locally(patch):
    bad = {**ENTRY, **patch}
    assert parse_mod_releases(json.dumps([bad]), VERSIONS, 1) == []
    assert len(parse_mod_releases(json.dumps([bad, ENTRY]), VERSIONS, 1)) == 1


def test_empty_non_objects_and_missing_fields():
    assert parse_mod_releases('[]', VERSIONS, 1) == []
    assert parse_mod_releases('[null, 1, true, [], {}]', VERSIONS, 1) == []
    assert parse_mod_releases(json.dumps([ENTRY]), {}, 1) == []


@pytest.mark.parametrize('escaped', [False, True])
def test_decode_once_preserves_author_text(escaped):
    entry = {**ENTRY, 'modVersionDisplayName': 'A &copy; &quot; B'}
    value = json.dumps([entry])
    result = parse_mod_releases(html.escape(value) if escaped else value, VERSIONS, 1)
    assert result[0].display_name == entry['modVersionDisplayName']
