"""Read only persisted PHP results. No rating formula, weights or voter data here."""
from decimal import Decimal
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlmodel import Session
from config import CONFIG


class RatingSummary(BaseModel):
    score: float | None = Field(ge=0, le=5)
    rating_count: int = Field(ge=0)


class RatingUnavailable(RuntimeError):
    pass


# Exact native empty form only: no PHP deserialization/evaluation, and no attempt
# to interpret arbitrary permission formulas. Any other nonempty value is denied.
_EMPTY_NATIVE_FORMULA = 'a:5:{i:0;s:0:"";i:1;s:0:"";s:7:"message";s:0:"";s:5:"medal";N;s:5:"users";s:0:"";}'


def public_forum(row, guest_access: int) -> bool:
    # Conservative guest ACL: never expose paid/password/formula/group-only content.
    # Parent categories and sub-forum ancestors must pass the same rules.
    if row is None or row['status'] != 1 or row['field_fid'] is None:
        return False
    has_formula = bool(row['formulaperm']) and row['formulaperm'] != _EMPTY_NATIVE_FORMULA
    if row['password'] or has_formula or row['price']:
        return False
    return ('7' in row['viewperm'].split('\t')) if row['viewperm'] else guest_access > 0


def _validate_tids(tids: list[int], maximum: int | None = None) -> None:
    if (maximum is not None and (not tids or len(tids) > maximum)) or any(
            type(tid) is not int or tid < 1 or tid > 4294967295 for tid in tids):
        raise ValueError('Require positive uint32 thread IDs within the batch limit')


def read_ratings(session: Session, tids: list[int]) -> dict[int, dict]:
    """Live HTTP batch remains capped at 100 and reevaluates guest access each call."""
    _validate_tids(tids, maximum=100)
    return _read_ratings(session, tids)


def read_rating_snapshot(session: Session, tids: list[int]) -> dict[int, dict]:
    """Internal full-list refresh: bounded ID chunks, shared ACL metadata, no N+1."""
    _validate_tids(tids)
    return _read_ratings(session, tids)


def _read_ratings(session: Session, tids: list[int]) -> dict[int, dict]:
    unique_tids = list(dict.fromkeys(tids))
    if not unique_tids:
        return {}
    # Fixed identifiers and bound IDs only; metadata is read once per full refresh.
    statement = text("""
        SELECT t.tid,t.fid,t.readperm,t.price,t.special,t.recommend_add,t.recommend_sub,
               s.tid AS summary_tid,s.rating_count,s.display_score,s.algorithm_version
        FROM pre_forum_thread t LEFT JOIN pre_forum_modrating_summary s ON s.tid=t.tid
        WHERE t.tid IN :tids AND t.displayorder>=0 AND t.sortid IN (1,2,3)
          AND t.fid IN :fids
    """).bindparams(bindparam('tids', expanding=True), bindparam('fids', expanding=True))
    fids = sorted(CONFIG['fossic']['mod_fids'] | CONFIG['fossic']['modding_fids'])
    threads = []
    for offset in range(0, len(unique_tids), 100):
        threads.extend(session.execute(statement,
            {'tids': unique_tids[offset:offset + 100], 'fids': fids}).mappings().all())
    # One small forum metadata query, not one query per Mod/ancestor.
    forums = session.execute(text("""
        SELECT f.fid,f.fup,f.type,f.status,ff.fid AS field_fid,
               ff.password,ff.viewperm,ff.formulaperm,ff.price
        FROM pre_forum_forum f LEFT JOIN pre_forum_forumfield ff ON ff.fid=f.fid
    """)).mappings().all()
    by_fid = {row['fid']: row for row in forums}
    guest_access = session.execute(text('SELECT readaccess FROM pre_common_usergroup_field WHERE groupid=7')).scalar_one()
    result = {}
    for thread in threads:
        if thread['readperm'] > guest_access or (thread['price'] > 0 and thread['special'] == 0):
            continue
        current, seen = thread['fid'], set()
        visible = True
        while current:
            if current in seen or len(seen) >= 3:
                visible = False
                break
            seen.add(current)
            forum = by_fid.get(current)
            if not public_forum(forum, guest_access) or (len(seen) == 1 and forum['type'] not in ('forum', 'sub')):
                visible = False
                break
            current = forum['fup']
        if not visible:
            continue
        if thread['summary_tid'] is None:
            if thread['recommend_add'] or thread['recommend_sub']:
                raise RatingUnavailable('Legacy seed missing')
            data = {'score': None, 'rating_count': 0}
        else:
            count, score = thread['rating_count'], thread['display_score']
            numeric_score = None if score is None else Decimal(str(score))
            if (thread['algorithm_version'] != 2 or type(count) is not int or count < 0
                    or (count < 10 and score is not None) or (count >= 10 and score is None)
                    or (numeric_score is not None and (not numeric_score.is_finite()
                        or not Decimal(0) <= numeric_score <= Decimal(5)))):
                raise RatingUnavailable('Invalid persisted summary')
            data = {'score': None if score is None else float(score), 'rating_count': int(count)}
        result[thread['tid']] = data
    return result
