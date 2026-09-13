# Mod 索引排序元数据调研与扩展方案

## 本轮确认实施范围

仅新增 thread_meta.heats、thread_meta.views、mod_releases[].download_count。附件缺失或跨帖时该项返回 null，前端逐项跳过，不影响同版本其他有效附件；有效计数为零仍属于有数据。全无有效附件时排序在有数据之后。不新增排序接口，不实现评分、回复、名称排序。用户随后授权提交、推送和生产部署，验证记录见 mod-releases.md。附件查询失败属于刷新失败，保留旧缓存，不能当作附件缺失。

2026-09-13：由前端索引排序需求驱动。本轮确认范围已完成实现、测试和上线；其余指标仍是调研方案。实施契约及验证记录见 mod-releases.md。

## 当前系统

实际论坛为 Discuz! X 3.5；接口为 Fossic-API（FastAPI + SQLModel + MySQL + 进程内缓存），当前查询路径没有 Elasticsearch。本文按这套实际系统设计。

已有 `thread_meta.recommend_weight`、`featured_level`，以及 `mod_update_date`。Release 已提供 attachment_id、game_version、mod_version 等映射，尚无下载统计。前端可以在缓存结果上完成筛选和排序。

## 指标算法与语义

- 推荐权重：API 的 recommend_weight 直接来自 forum_thread.recommends。每次支持增加用户组 allowrecommend 的分值，每次反对减去该分值；recommend_add / recommend_sub 分别增加 1。重复推荐由 forum_memberrecommend 检查，是否允许自荐、每日次数和权限受配置控制。因此推荐权重不是点赞人数，也不是简单的支持数减反对数。
- 热度 heats：update_threadpartake 对登录用户参与行为加 1。配置 period 非零时，通过 threadpartake 的 tid/uid 判断是否已经参与；type=2 且 period 非零时，每日清理超过周期的参与记录，之后用户可以再次贡献热度。清理不扣除已经累积的 heats；period=0 时每次调用都可增加。回复、点评、推荐、收藏、分享存在调用点。它是累积参与热度，不是带时间衰减的近期热榜，也不是严格的独立回复人数。
- 浏览量 views、回复数 replies 是帖子表已有计数。浏览量受 preventrefresh、optimizeviews 等配置影响，不是独立访客数；启用 optimizeviews 时部分增量暂存在 threadaddviews，之后批量合并。第一版读取已落帖子表的 views，接受统计延迟，不增加实时合并逻辑。
- 下载次数：附件索引表 forum_attachment.downloads，aid 为主键。现有 boan_oss 下载处理保留计数逻辑；可能通过日志延迟落库，Range、requestmode、noupdate 等条件会影响计数。它表示论坛记录的附件下载次数，不保证完成下载，不是独立下载人数，也不覆盖绕过论坛的外链/CDN 访问。
- 其它低成本指标：精华等级 digest、发帖时间 dateline、最后活动时间 lastpost。lastpost 会被推荐等行为更新，不应命名为 Mod 更新时间或严格的最后回复时间。

以上算法来自本地论坛源码；本轮未读取生产后台的 heatthread、用户组推荐分值等实际配置，不能把默认值当作本站当前值。

## 建议字段

### 评分星币与顶踩的区别（补充调研）

评分走 forum_misc.php 的 rate 流程，更新被评分帖作者的扩展积分，按配置可能扣评分者自身积分，并逐积分类型写入 forum_ratelog。它不更新 recommends/recommend_add/recommend_sub；与顶踩是独立机制，但评分也会调用 update_threadpartake，可能贡献参与热度。

forum_ratelog 记录 pid、评分者 uid、extcredits（积分类型）、score（可正可负）、dateline、reason，并有 (pid, dateline) 索引。星币具体对应哪个 extcredits 必须核实本站配置，不能写死猜测。

Mod 排序建议只统计发布帖首楼，避免混入回复楼层获赠的星币。按目标首楼 pid 批量聚合指定积分类型：SUM(score) 为净评分星币；SUM(CASE WHEN score > 0 THEN score ELSE 0 END) 为正向评分总额；COUNT(DISTINCT CASE WHEN score > 0 THEN uid END) 为当前记录中的正向评分人数。同一人可能有多条记录，不能用记录条数代替人数。撤销评分会删除对应 ratelog，因此以上代表当前保留的评分，不是不可撤销的历史总量。

不能直接使用 forum_thread.rate 当作星币总额：首楼评分时这里只写入汇总分值的符号（-1/0/1）。forum_post.rate 也不是按星币类型独立统计，精确星币指标应使用指定 extcredits 的日志聚合。

获取首楼 pid 时仅查目标 tid 的首楼，注意 posttableid 分表路由；再按这些 pid 利用 ratelog 索引批量汇总，随缓存定时刷新，不对每次访客请求执行聚合。实施时核实索引、权限和 EXPLAIN，统计开销较读取现成计数高，应实测后决定刷新周期。现有 API 尚未暴露这些评分数据。

在 thread_meta 增加 views、replies、heats、recommend_add、recommend_sub，保留原 recommend_weight 与 featured_level。ModRelease 增加 download_count: int | null；0 表示查到附件且计数为零，null 表示缺失或无法确认，不能伪装为零。

优先提供最近更新、推荐最多、参与热度最高、浏览最多、回复最多、所选游戏版本下载最多。回复人数暂不提供，避免扫描帖子明细做 COUNT DISTINCT。近期热门需要在 API 自己的存储中保存周期快照并计算增量，作为后续需求，不能用累积 heats 冒充。

## 查询与缓存

1. 复用 ModDAO.get_all_mods 已有的 ForumThread JOIN，多选几个计数列即可，不为每个 Mod 单独查询帖子，不添加数据库排序或分页查询。
2. 解析并验证 Release 后，仅收集有效索引条目的附件 ID，去重；按有界批次（例如 500 个）查询附件索引表的 aid、tid、downloads。典型几百个发布项仅增加一至数次查询，而不是数百次。
3. 利用 aid 主键查找，不遍历附件分表、不读取文件路径或正文、不扫描全站附件。返回后还必须校验附件 tid 与 Release 所属帖子一致，防止作者填写其它帖子的 aid 混入统计。缺失/不匹配返回 null。
4. 同一 attachment_id 跨多个已选版本重复映射时只计一次。按所选游戏版本筛出匹配 Release 后再汇总；没有映射的 Mod 记为未知。该值只代表当前映射的发布附件，替换上传后的新 aid 不能承接旧附件历史总下载量。
5. 所有补查仅在现有 ModCache 刷新中执行。默认 MOD_CACHE_TIME=300 秒，APScheduler 已设置 max_instances=1/coalesce，成功后整体替换快照并清 HTTP 响应缓存；失败保留旧快照，不能清零统计。普通访客请求只读内存，不增加 SQL。
6. 当前缓存是进程内的；以后多 worker/多副本会各自刷新。扩容前再评估单刷新任务与共享快照，无需为当前规模引入 Elasticsearch。

## 实施前检查与验证

- 核实生产只读 API 账号是否有附件索引表 SELECT 权限；若缺失，只增加该表的必要只读权限，不能授予写权限。
- 对新增附件批查运行 EXPLAIN，确认 aid 主键访问；对照上线前后的刷新耗时、SQL 次数、慢查询、数据库 CPU。少选列和批量查询降低开销，但性能结论应以实测为准。
- 验证批次边界、重复 aid、跨帖 aid、缺失附件、无 Release、零下载、查询失败保留旧缓存，以及请求命中缓存时零 SQL。
- 确认已有字段和 Release 映射语义不变，更新 OpenAPI/接口文档；前端排序另行实施。

## 源码依据

- Fossic-API：src/dao.py、src/models.py、src/cache.py、src/main.py、src/config.py、src/mod_releases.py。
- FossicDiscuz：upload/source/module/forum/forum_misc.php（推荐）、upload/source/function/function_forum.php（update_threadpartake）、upload/source/include/cron/cron_cleanup_daily.php（去重记录清理）。
- FossicDiscuz：upload/source/module/forum/forum_viewthread.php（浏览计数）、upload/source/plugin/boan_oss/source/discuz/forum_attachment.php（实际插件附件计数）、upload/source/class/table/table_forum_attachment.php、upload/install/data/install.sql（字段与主键）。
