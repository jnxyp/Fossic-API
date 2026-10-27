import math

import pytest
from pydantic import ValidationError

from mod_recommendation import calculate_recommendation_score, freshness_bonus
from models import ModInfoOriginal, ModRelease

NOW = 1_800_000_000


def release(aid=1, count=0, version='0.98'):
    return ModRelease(attachment_id=aid, game_version_id='v', game_version=version,
                      mod_version='1', download_count=count)


def mod(**patch):
    return ModInfoOriginal(**{
        'mod_id': 'test', 'mod_name_cn': '测试', 'mod_version': '1',
        'mod_safe_remove': False, 'mod_short_description': '', 'mod_language': 'chinese',
        'mod_update_date': NOW, 'mod_publish_urls': [], 'mod_category': 'utility',
        'admin_notes': {}, 'thread_meta': {'title': 'test', 'tid': 1, 'uid': 1, 'fid': 46,
            'featured_level': 0, 'recommend_weight': 0, 'heats': 0, 'views': 0}, **patch,
    })


@pytest.mark.parametrize('days,expected', [
    (0, 5), (3, 3.2), (5, 20 / 9), (7.5, 1.25), (10, 5 / 9), (15, 0), (30, 0),
])
def test_freshness_boundaries(days, expected):
    assert freshness_bonus(NOW - int(days * 86400), now=NOW) == pytest.approx(expected)


@pytest.mark.parametrize('seconds', [1, 15 * 86400 - 1, 15 * 86400, 15 * 86400 + 1])
def test_quadratic_window_at_second_precision(seconds):
    remaining = max(0, 1 - seconds / (15 * 86400))
    bonus = freshness_bonus(NOW - seconds, now=NOW)
    assert bonus == pytest.approx(5 * remaining ** 2, abs=1e-15)
    if 0 < remaining < 1:
        assert bonus < 5 * remaining


@pytest.mark.parametrize('timestamp', [None, -1, 0, True, False, '2026-01-01',
                                       math.nan, math.inf, -math.inf, 1.5])
def test_invalid_dates_have_no_bonus(timestamp):
    assert freshness_bonus(timestamp, now=NOW) == 0


def test_future_dates_are_capped():
    assert freshness_bonus(NOW + 86400, now=NOW) == 5


def test_score_matches_formula_and_does_not_mutate_input():
    item = mod(mod_download_count=999, mod_releases=[release(1, 99), release(2, 900)],
               mod_update_date=NOW - int(7.5 * 86400))
    before = item.model_dump()
    assert calculate_recommendation_score(item, now=NOW) == pytest.approx(4.25)
    assert item.model_dump() == before
    assert item.mod_recommendation_score == 0  # DAO default is not the computed response score.


def test_score_is_independent_per_mod_and_of_version_language_download_switch():
    first = mod(mod_download_count=99, mod_releases=[release(1, 99)])
    second = first.model_copy(update={'mod_game_versions': ['0.97'],
                                     'mod_language': 'english', 'mod_allow_direct_download': True})
    assert calculate_recommendation_score(first, now=NOW) == 7
    assert calculate_recommendation_score(second, now=NOW) == 7


def test_score_monotonicity_and_permanent_download_floor():
    scores = [calculate_recommendation_score(mod(mod_download_count=n, mod_releases=[release(count=n)]), now=NOW)
              for n in [0, 10, 100, 1000, 10000]]
    assert scores == sorted(scores)
    item = mod(mod_download_count=999, mod_releases=[release(count=999)])
    timed = [calculate_recommendation_score(item, now=NOW + day * 86400)
             for day in [0, 1, 7, 15, 365]]
    assert timed == sorted(timed, reverse=True)
    assert timed[-2:] == [3, 3]


@pytest.mark.parametrize('score', [-1, math.nan, math.inf, -math.inf])
def test_model_rejects_invalid_score(score):
    with pytest.raises(ValidationError):
        mod(mod_recommendation_score=score)


def test_score_uses_persistent_total_not_current_releases():
    assert calculate_recommendation_score(mod(mod_download_count=999, mod_releases=[]), now=NOW) == 8
    assert calculate_recommendation_score(mod(mod_download_count=0, mod_releases=[release(count=999)]), now=NOW) == 5


@pytest.mark.parametrize('field', ['mod_download_count', 'mod_excluded_download_count'])
@pytest.mark.parametrize('value', [-1, True, 1.5, '3'])
def test_model_rejects_invalid_persistent_counts(field, value):
    with pytest.raises(ValidationError):
        mod(**{field: value})
