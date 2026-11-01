# Mod rating read API — FossicDiscuz #49

Requires the companion forum migration and PHP rating implementation. This API never computes or writes ratings.

- `GET /mods/{tid}/rating` → exactly `{"score":4.47,"rating_count":23}`. Below ten ratings: `score:null`; ten zero ratings: `score:0`. A new unrated thread returns NULL/0. A missing summary with existing legacy votes is a migration error (503), not an empty result.
- `GET /mods/ratings?tid=123&tid=456` → ID-keyed objects of the same two fields. 1–100 IDs; omit nonpublic/non-Mod/missing IDs. Invalid IDs/oversized batch return 422. No user IDs, raw mean, weights, distribution, own score or other details.
- Single absent/private/non-Mod: 404. Unavailable schema/query, unsupported algorithm or inconsistent persisted summary: 503, never a fabricated zero.
- PHP persists full precision `score` and rounded `display_score`; we select `display_score`, with no Python/frontend copy of the weighting/root formula.
- Scope uses configured formal + Modding board IDs, not the narrower indexed Mod list. No Mod-index UI or existing ranking changes.
- Thread visibility, read permission and thread paywall must allow the guest group. Forum + up to two ancestor levels must be public; deny password, formula, paid/forum-group/closed boards, missing metadata and cycles. Nonempty viewperm must explicitly contain group 7. Guest readaccess is read from the native group table. This deliberately conservative endpoint does not infer a user's special access grant.
- A bounded batch uses three SELECTs: thread+summary join, small forum metadata set, guest readaccess. No per-thread/ancestor N+1 reads, no detail-table aggregate scanning.
- Routes run synchronous DB work in FastAPI's worker thread pool. No shared cache/snapshot is used for ratings: every request reevaluates guest access; HTTP responses are `Cache-Control: no-store`. Existing `/mods` snapshot caching is unchanged. Consumers should use batches and avoid polling unbounded lists.

## Deployment / SELECT-only privileges

Deploy the forum's guarded implementation, drain legacy Mod recommendation writes, seed, then enable ratings according to its `docs/mod-rating.md`. Do not enable merely because the schema exists. This document authorizes no production deployment.

The existing API DB user needs SELECT on four additional tables:

- `pre_forum_modrating_summary`
- `pre_forum_forum`
- `pre_forum_forumfield`
- `pre_common_usergroup_field`

Retain existing `pre_forum_thread` SELECT; **do not grant write, DDL, detail rating table or user/member-table access**. Query failures after missing grants return 503. Rollback API code without dropping forum rating data. Forum/API algorithm version 2 contract must remain aligned; algorithm or threshold changes require a reviewed backend recomputation, not a local Python formula.

## Tests

`python -m pytest -q tests/test_ratings.py` uses isolated SQLite, never a developer/production DB. Covers 0 vs NULL, exact public payload, bounded queries, all three Mod sorts, Modding and guest group matching, parent ACL, private/missing/deleted threads, corrupt/missing migration results, batch limits and storage failure. Existing API regressions must also pass.

Real FPM/MySQL/API + sandboxed Windows Chrome integration lives in the companion forum's `tests/mod-rating-local-stack.cjs` and uses only owned synthetic LocalStack fixtures. No real business data or credentials enter Git.

## Algorithm v2 alignment (pending deployment)

The forum compresses each frozen historical counter separately: U=ceil(sqrt(up)), D=ceil(sqrt(down)); effective legacy count U+D, legacy score sum 4U. New votes retain native group-weight snapshots and are not compressed. The ten-rating gate uses effective legacy count plus new voter count. Public `rating_count` is therefore an effective count, not raw historical voters. PHP still owns all score computation; this API only accepts persisted algorithm_version=2. Pre-release v1 rows produce503 until the forum's explicit guarded rebase-legacy upgrade completes; do not accept mixed versions or recalculate in Python.

## Native empty permission wrapper compatibility

Production boards store the native five-field empty `formulaperm` wrapper (empty text/expression/message/users, NULL medal), not an empty SQL string. The read API recognizes only that exact canonical serialization as unrestricted. Arbitrary serialization, objects, unknown/extra fields, whitespace variants, malformed input and nonempty expression/user/medal rules remain denied; no PHP deserializer or formula evaluator is added. Board/password/readaccess/paywall/ancestor checks and the three-query bound remain unchanged. No production permission setting or stored rule is edited.
