"""Pure Mod recommendation scoring; the snapshot refresh owns the clock."""
import math

from models import ModInfoTypes

FRESHNESS_BONUS = 5.0
FRESHNESS_WINDOW_SECONDS = 15 * 86400


def freshness_bonus(update_timestamp: int | None, *, now: int) -> float:
    """Decay quadratically over 15 days; unknown dates earn no bonus, future dates cap at five."""
    if type(update_timestamp) is not int or update_timestamp <= 0:
        return 0.0
    age = max(0, now - update_timestamp)
    return FRESHNESS_BONUS * max(0, 1 - age / FRESHNESS_WINDOW_SECONDS) ** 2


def calculate_recommendation_score(mod: ModInfoTypes, *, now: int) -> float:
    """Return one finite score per Mod, independent of filters and language."""
    score = math.log10(1 + mod.mod_download_count) + freshness_bonus(
        mod.mod_update_date, now=now)
    if not math.isfinite(score) or score < 0:
        raise ValueError('Invalid Mod recommendation score')
    return score
