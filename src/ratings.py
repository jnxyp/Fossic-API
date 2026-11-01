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


def public_forum(row, guest_access: int) -> bool:
    # Conservative guest ACL: never expose paid/password/formula/group-only content.
    # Parent categories and sub-forum ancestors must pass the same rules.
    if row is None or row['status'] != 1 or row['field_fid'] is None:
        return False
    if row['password'] or row['formulaperm'] or row['price']:
        return False
    return ('7' in row['viewperm'].split('\t')) if row['viewperm'] else guest_access > 0


def read_ratings(session: Session, tids: list[int]) -> dict[int, dict]:
    if not tids or len(tids) > 100 or any(tid < 1 or tid > 4294967295 for tid in tids):
        raise ValueError('Require 1–100 positive thread IDs')
    # Fixed table identifiers; only expanding, bound ID lists enter the SQL.
    threads = session.execute(text("""
        SELECT t.tid,t.fid,t.readperm,t.price,t.special,t.recommend_add,t.recommend_sub,
               s.rating_count,s.display_score,s.algorithm_version
        FROM pre_forum_thread t LEFT JOIN pre_forum_modrating_summary s ON s.tid=t.tid
        WHERE t.tid IN :tids AND t.displayorder>=0 AND t.sortid IN (1,2,3)
          AND t.fid IN :fids
    """).bindparams(bindparam('tids', expanding=True), bindparam('fids', expanding=True)),
        {'tids': list(set(tids)), 'fids': sorted(CONFIG['fossic']['mod_fids'] | CONFIG['fossic']['modding_fids'])}).mappings().all()
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
        if thread['rating_count'] is None:
            if thread['recommend_add'] or thread['recommend_sub']:
                raise RatingUnavailable('Legacy seed missing')
            data = {'score': None, 'rating_count': 0}
        else:
            count, score = thread['rating_count'], thread['display_score']
            if (thread['algorithm_version'] != 2 or count < 0
                    or (count < 10 and score is not None) or (count >= 10 and score is None)
                    or (score is not None and not Decimal(0) <= Decimal(str(score)) <= Decimal(5))):
                raise RatingUnavailable('Invalid persisted summary')
            data = {'score': None if score is None else float(score), 'rating_count': int(count)}
        result[thread['tid']] = data
    return result
