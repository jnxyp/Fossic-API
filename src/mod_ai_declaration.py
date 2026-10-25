"""Read untrusted forum declarations; never infer non-use from unknown data."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from phpserialize import loads

import log
from models import ModAiDeclaration
from mod_releases import unescape_discuz_json

if TYPE_CHECKING:
    from tables import ForumTypeOption, ForumTypeOptionVar

logger = log.get_logger(__name__)
MAX_BYTES = 2048
DIMENSIONS = ('code', 'art', 'audio', 'text')
KEYS = {'status', *DIMENSIONS}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Nonstandard JSON constant')


def parse_mod_ai_declaration(value: str | None, tid: int) -> ModAiDeclaration:
    if value is None:
        return ModAiDeclaration.undeclared()
    try:
        # Each supported source entity takes at most six characters per decoded byte.
        if not isinstance(value, str) or len(value) > MAX_BYTES * 6:
            raise ValueError('Invalid or oversized declaration')
        raw = unescape_discuz_json(value)
        if len(raw.encode('utf-8')) > MAX_BYTES:
            raise ValueError('Oversized declaration')
        if not raw.strip():
            return ModAiDeclaration.undeclared()
        data = json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        if not isinstance(data, dict) or set(data) != KEYS:
            raise ValueError('Expected exactly five declaration fields')
        # Validate the forum representation BEFORE changing its undeclared dimensions.
        if data['status'] == 'undeclared':
            if not all(data[key] == 'none' for key in DIMENSIONS):
                raise ValueError('Invalid source undeclared dimensions')
            return ModAiDeclaration.undeclared()
        return ModAiDeclaration.model_validate(data)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        # Do not log validation messages: they may contain publisher-controlled input.
        logger.warning('帖子 %s modAiDeclaration 无效 (%s)，返回未声明',
                       tid, type(error).__name__)
        return ModAiDeclaration.undeclared()


def is_public_ai_option(option: ForumTypeOption, value: ForumTypeOptionVar,
                        now: int) -> bool:
    if option.expiration and value.expiration and value.expiration <= now:
        return False
    if not option.protect:
        return True
    try:
        if len(option.protect) > 4096:
            return False
        protection = loads(option.protect.encode('utf-8'))
        # Conservative public projection: never attempt user-group/verification auth.
        return (isinstance(protection, dict)
                and protection.get(b'status') in (b'0', 0, False)
                and not protection.get(b'usergroup')
                and not protection.get(b'verify'))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False
