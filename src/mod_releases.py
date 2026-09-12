"""Parse untrusted Discuz release metadata without breaking cache refreshes."""

import json
import re

import log
from models import ModRelease

logger = log.get_logger(__name__)

# Match PHP htmlspecialchars_decode(..., ENT_QUOTES), once, without decoding
# unrelated entities inside author-supplied strings (e.g. &copy;).
_ENTITIES = {'&amp;': '&', '&quot;': '"', '&#039;': "'", '&#39;': "'",
             '&lt;': '<', '&gt;': '>'}
_ENTITY_PATTERN = re.compile('|'.join(re.escape(key) for key in _ENTITIES))


def parse_mod_releases(
    value: str | None, game_versions: dict[str, str], tid: int,
) -> list[ModRelease] | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        # Plain JSON may legitimately contain literal entity text in strings.
        # Decode HTML only when the original value is not already valid JSON.
        try:
            entries = json.loads(value)
        except ValueError:
            decoded = _ENTITY_PATTERN.sub(lambda match: _ENTITIES[match[0]], value)
            entries = json.loads(decoded)
        if not isinstance(entries, list):
            raise ValueError('expected a JSON array')
    except (TypeError, ValueError, RecursionError):
        logger.warning('帖子 %s modReleaseFilesMapping 无法解析为 JSON 数组', tid)
        return None

    releases = []
    rejected = 0
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                raise ValueError('expected an object')
            aid = entry.get('aid')
            if isinstance(aid, str) and re.fullmatch(r'[0-9]+', aid):
                aid = int(aid)
            # Discuz attachment IDs are unsigned MySQL INTs. Reject bool/float.
            if type(aid) is not int or not 0 < aid <= 4294967295:
                raise ValueError('invalid attachment ID')
            version_id = entry.get('gameVersion')
            if not isinstance(version_id, str) or version_id not in game_versions:
                raise ValueError('unknown game version')
            version = entry.get('modVersion')
            if not isinstance(version, str) or not version.strip():
                raise ValueError('empty mod version')
            display = entry.get('modVersionDisplayName')
            if display is not None and not isinstance(display, str):
                raise ValueError('invalid display name')
            release = ModRelease(
                attachment_id=aid, game_version_id=version_id,
                game_version=game_versions[version_id], mod_version=version.strip(),
                display_name=(display.strip() or None) if display else None,
            )
            # Reject lone JSON surrogates before they can break HTTP encoding.
            release.model_dump_json().encode('utf-8')
            releases.append(release)
        except (TypeError, ValueError, UnicodeError):
            rejected += 1
    if rejected:
        logger.warning('帖子 %s modReleaseFilesMapping 已过滤 %s/%s 个无效条目',
                       tid, rejected, len(entries))
    return releases
