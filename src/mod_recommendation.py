"""Pure Mod recommendation scoring; the snapshot refresh owns the clock."""
import math

from models import ModInfoTypes, ModRelease

FRESHNESS_BONUS = 5.0
FRESHNESS_WINDOW_SECONDS = 15 * 86400


def total_download_count(releases: list[ModRelease] | None) -> int:
    """Sum registered files across all versions, counting each attachment once."""
    seen: set[int] = set()
    total = 0
    for release in releases or []:
        aid, count = release.attachment_id, release.download_count
        if (type(aid) is not int or aid <= 0
                or type(count) is not int or count < 0 or aid in seen):
            continue
        seen.add(aid)
        total += count
    return total


def freshness_bonus(update_timestamp: int | None, *, now: int) -> float:
    """An unknown date earns no bonus; future dates cannot exceed five points."""
    if type(update_timestamp) is not int or update_timestamp <= 0:
        return 0.0
    age = max(0, now - update_timestamp)
    return FRESHNESS_BONUS * max(0, 1 - age / FRESHNESS_WINDOW_SECONDS)


def calculate_recommendation_score(mod: ModInfoTypes, *, now: int) -> float:
    """Return one finite score per Mod, independent of filters and language."""
    score = math.log10(1 + total_download_count(mod.mod_releases)) + freshness_bonus(
        mod.mod_update_date, now=now)
    if not math.isfinite(score) or score < 0:
        raise ValueError('Invalid Mod recommendation score')
    return score
