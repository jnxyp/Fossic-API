# Mod rating read API — FossicDiscuz #49

Requires the companion forum migration and PHP rating implementation. This API never computes or writes ratings.

- `GET /mods/{tid}/rating` → exactly `{"score":4.47,"rating_count":23}`. Below ten ratings: `score:null`; ten zero ratings: `score:0`. A new unrated thread returns NULL/0. A missing summary with existing legacy votes is a migration error (503), not an empty result.
- `GET /mods/ratings?tid=123&tid=456` → ID-keyed objects of the same two fields. 1–100 IDs; omit nonpublic/non-Mod/missing IDs. Invalid IDs/oversized batch return 422. No user IDs, raw mean, weights, distribution, own score or other details.
- Single absent/private/non-Mod: 404. Unavailable schema/query, unsupported algorithm or inconsistent persisted summary: 503, never a fabricated zero.
- PHP persists full precision `score` and rounded `display_score`; we select `display_score`, with no Python/frontend copy of the weighting/root formula.
- Scope uses configured formal + Modding board IDs, not the narrower indexed Mod list. No Mod-index UI or existing ranking changes; list integration is described below.
- Thread visibility, read permission and thread paywall must allow the guest group. Forum + up to two ancestor levels must be public; deny password, formula, paid/forum-group/closed boards, missing metadata and cycles. Nonempty viewperm must explicitly contain group 7. Guest readaccess is read from the native group table. This deliberately conservative endpoint does not infer a user's special access grant.
- A bounded batch uses three SELECTs: thread+summary join, small forum metadata set, guest readaccess. No per-thread/ancestor N+1 reads, no detail-table aggregate scanning.
- Routes run synchronous DB work in FastAPI's worker thread pool. These independent rating routes do not use a shared cache/snapshot: every request reevaluates guest access; their HTTP responses are `Cache-Control: no-store`. The list field below instead follows `/mods` snapshot caching. Consumers should use batches and avoid polling unbounded lists.

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


## Mod list rating summary — API #12 (implementation, not deployed)

`GET /mods` and `GET /mods?include_modding=true` include the same `mod_rating`
field on original, translated and reposted Mods. Games do not receive this field.

```json
{"mod_rating":{"score":4.47,"count":10}}
```

- `score` is the persisted PHP `display_score`, 0–5, at most two decimal places;
  neither Python nor the frontend recomputes the forum rating formula.
- `count` maps to the existing effective `rating_count`: compressed historical
  votes plus new voter count, not an independently verified historical user count.
- Below ten effective ratings: `{"score":null,"count":9}`. Public, unrated and
  without unmigrated legacy votes: `{"score":null,"count":0}`. At or above ten,
  a genuine zero score stays zero, not null.
- When guest access is denied or the thread is no longer eligible, the entire
  `mod_rating` is null. This does not change the existing list's item filtering.
  No user identity, own vote, weights, raw mean or vote distribution is returned.
- Lists follow the existing `MOD_CACHE_TIME` snapshot interval (default 300s).
  Scores **and guest ACL results can remain stale until a successful refresh**;
  refresh errors retain the old snapshot and timestamp, possibly longer than one
  interval. Use `/status` to check freshness. Use the independent no-store rating
  routes when current guest permission and score are required; their payload
  remains `{score,rating_count}` and their public batch limit remains 100.

Refresh reuses the live reader's conservative guest/ancestor ACL checks and
algorithm-version validation. It deduplicates the complete list, queries joined
thread/summary rows in bound batches of at most 100 IDs, and reads forum metadata
and guest permissions once: `ceil(unique_ids/100) + 2` rating SELECTs for nonempty
lists, zero for empty lists. No detail-table aggregates or additional DB grants
are required. All forum reads finish before the SQLite download-statistics write
transaction. Missing schema/grants, corrupt summaries, unsupported algorithms or
missing legacy seeds fail the Mod refresh without publishing partial data or
fabricating zero ratings; games refresh independently. No new request-time list
SQL, writes to forum tables, migrations or deployment settings are added.

### Removed metadata (breaking response change)

Both Mod **and game** responses and OpenAPI remove `thread_meta.recommend_weight`
and `thread_meta.heats`, with no compatibility aliases. Consumers must stop
reading these fields. `views`, `featured_level` and the download/freshness-based
`mod_recommendation_score` are unchanged. Native forum database columns and
heat/recommendation behavior remain intact. The companion official index cleanup
removes only unused types/test fixtures; third-party clients may still depend on
the removed fields and are outside that audit's visibility.

### Local regression coverage

`python -X utf8 -m pytest -q` includes `tests/test_mod_rating_snapshot.py`:
all Mod sorts/Modding and games, OpenAPI removals, threshold/zero/null semantics,
live-versus-snapshot freshness, ancestor ACL and exact empty permission wrapper,
501-ID bounded bulk reads and public cap, invalid summary/model data, and failed
refresh preserving the full old snapshot without entering a stats transaction.
Tests use synthetic SQLite data, not production DB access. This implementation
and its tests do not authorize or establish a production deployment.
