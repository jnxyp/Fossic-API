# Mod 持久下载统计

状态：对应 issue #4 的实现，待 PR 审核及单独部署；不表示生产已启用。仅修改后端，不改前端，不新增统计查询接口。

## 统计规则

以 `thread_meta.tid` 为发布项主键，原创/汉化/转载不同帖子独立；`mod_id` 不作为主键。附件账本按 `(tid, attachment_id)` 唯一。所有游戏版本累计，当前与历史附件贡献均参与总量。

```text
delta = max(0, 本轮有效源计数 - 已入账高水位)
高水位 = max(旧高水位, 本轮有效源计数)
```

- 新附件旧高水位为0；首次上线、后来补登记的已有下载数全部计入本轮周期，不区分历史基线。
- **取消登记后，即使源文件仍在，也停止跟踪**，冻结已入账贡献。不会查询未登记的历史附件或扫描本帖所有文件。
- 重新登记沿用账本，只补超过旧高水位的差额；退出期间的增长无法分拆，补入重新登记所在周期。
- 删除、归属不匹配、未知或无效计数不减历史；0是有效观测。源计数回退保留高水位并告警，追平前不新增，不自动识别重置。
- 整个帖子退出索引后保留统计、暂停采集；返回后继续。含Modding全量先采集，再派生默认列表，不受请求筛选影响。
- 论坛校验仍由既有 DAO/附件元数据填充完成；统计直接复用同轮 release.download_count，不增加论坛SQL，也不改变文件元数据、直链权限及null语义。

### 游戏版本

每个附件账本存一个 `game_version_id` 和最后已知名称，来自其当前有效release。论坛编辑器/校验规则不允许同一aid重复关联不同游戏版本。

取消登记保留最后归属；同版本换文件则新旧贡献一起保留。作者把同aid从A改到B时，整个历史贡献改归B，不增加总量或产生虚假增量；本轮源计数的真实增加仍正常入账。版本小计会因重新归类发生迁移，不等于总量下降。未来按版本统计历史周期同样使用最后有效归属，不保存归属时间线。

同轮重复同版本同计数去重；版本、名称或计数冲突则刷新失败、保留旧快照，不任意挑选。名称更新选同版本最近有效观测值。不会从mod_game_versions整体声明推断附件版本。

## `/mods` 字段

原创/汉化/转载均公开以下累计字段；按游戏版本的下载汇总暂不公开，内部账本与版本统计继续保留：

| 字段 | 类型 | 语义 |
|---|---|---|
| mod_download_count | 非负整数 | 本帖全部已入账附件贡献，包括冻结历史 |
| mod_excluded_download_count | 非负整数 | 未被当前releases有效计数覆盖的历史贡献 |

```json
{
  "mod_download_count": 1700,
  "mod_excluded_download_count": 1000,
  "mod_releases": [
    {"attachment_id": 20002, "game_version_id": "v98", "download_count": 700}
  ]
}
```

示例为局部字段，版本ID为示意。公开响应的对账恒等式：

```text
R = 当前返回releases有效下载计数按aid去重之和（null不参与）
E = mod_download_count - R
R + mod_excluded_download_count = mod_download_count
```

E不单独入库、不重复入账。正常时就是删除/排除或当前无有效计数附件的历史贡献；**源计数回退时，也包含在册附件历史高水位与当前源数的差额**。例如总量1700、冻结旧附件1000、在册附件从700退至650：总量仍1700，R=650，E=1050；这不是物理删除文件计数。负E直接令本轮失败，不能用max(0,...)掩盖错误。

`mod_releases[].download_count`仍为真实源数或null；`mod_game_versions`仍为当前兼容声明。推荐分改用持久mod_download_count，公式5分/15天不变，跨版本统一计分。默认和完整列表复用同一结果，不改变数组顺序。时间仍复用 `/status.cache.mods.last_updated`，不加calculated_at、周期查询接口或日期参数。

## 三张表及一致性

按最后有效游戏版本归属的累计小计仍在内部汇总及对账，包含历史版本，不影响采集和持久化；`/mods` JSON 和 OpenAPI 均不提供 `mod_download_counts_by_game_version`，也不增加版本统计查询接口。

权威DDL在 `src/download_stats.py::SCHEMA`，首版 `PRAGMA user_version=1`。不与论坛SQLModel metadata共享。

| 表 | 主键 | 主要列 |
|---|---|---|
| mod_download_totals | tid | total_download_count, tracking_started_at, last_observed_at |
| mod_download_attachments | tid, attachment_id | game_version_id, game_version, counted_download_count, first_observed_at, last_observed_at |
| mod_download_attachment_stats | tid, attachment_id, period_start | period_end, download_increment, first_observed_at, last_observed_at |

有外键，不设置删除级联；所有计数约束为SQLite非负整数（最多2^63−1），溢出不提交。版本索引 `(tid,game_version_id)`，周期索引 `(tid,period_start)`。

周期为 `[period_start,period_end)` Unix秒。第一版 `get_stats_period(now)` 取北京时间UTC+8自然日，字段与表名不绑定daily。未来改粒度必须在明确边界接续，旧周期不能重叠，同起点不同终点不能覆盖；粗粒度历史不能恢复为细粒度。当前不提供随意改粒度配置。

有效观测且无增长也写0并更新时间；退出登记、缺失、无效不伪造0或更新附件观测时间。缺行不等于0，有行不等于周期全程连续采集。全局停机后的增长计入恢复周期，不回填。轮询间隔中先增长后删除的数字和上线前已丢失附件无法恢复，不是精确事件账单或滚动24小时。

快照刷新顺序：论坛所有读取→统一now→BEGIN IMMEDIATE→账本/周期/总量更新→汇总及对账→评分、模型校验和全部响应编码→COMMIT→发布快照。总量必须等于附件贡献和、周期增量和、各版本小计和。SQLite错误、溢出、对账或编码失败回滚，保留旧Mod快照和时间；游戏独立刷新。不能故障回退瞬时求和。

每操作独立连接，foreign_keys=ON，synchronous=FULL，WAL，默认锁等待5秒；运行期使用mode=rw，文件丢失不会静默重建。初始化失败阻止启动，未知版本/非空未标记库/损坏库不重建。数据库提交和内存发布不是跨资源事务；提交后进程退出，下次高水位保证不重复入账。只支持单采集实例，不能额外启动多个workers争抢调度。

## 本地与Compose前置条件

本地默认 `DOWNLOAD_STATS_DB_PATH=data/download-stats.sqlite3`，从仓库根目录启动；先手工创建父目录，不覆盖已有数据库。Windows例如：

```powershell
# 以下路径相对于仓库根目录
New-Item -ItemType Directory -Force -Path .\data
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -X utf8 -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000
```

Compose强制容器路径 `/data/download-stats.sqlite3`，新增 `./data:/data`；`.env.sample`的本地相对路径不会覆盖容器路径。根目录及源码仍只读，持久数据只用bind mount。部署前先核对实际镜像运行UID/GID（当前Dockerfile定义10001:10001），为专用data及backups目录赋正确属主和合理权限；不递归修改其他目录。不要直接compose up让Docker生成root属主目录后再以777兜底。

论坛账号权限不变。数据库/WAL/SHM及备份从Git和Docker构建上下文排除。

## 一致性备份及恢复

提供本地管理命令（不是HTTP接口），使用sqlite3 backup API，并校验备份；先写同目录临时文件、成功后原子替换旧备份。默认最长120秒，失败保留旧文件，不创建源库，禁止覆盖源库或带journal侧文件的活跃目标。备份目录需提前按服务用户准备，不允许其他进程同时写同一备份目标。

```bash
# 以下命令从仓库根目录运行；具体生产执行须先读节点README
# /data/backups 必须由服务用户可写，不在本命令自动创建
# Compose exec 默认沿用镜像非root用户
docker compose exec -T fossic-api python -m download_stats \
  --source /data/download-stats.sqlite3 \
  --backup /data/backups/download-stats.sqlite3
```

也可在配置好依赖和PYTHONPATH=src的本地虚拟环境执行同一模块。备份源使用只读连接，不调用initialize或修改计数。备份操作可与正常采集同时运行，包含尚未checkpoint的已提交WAL内容。**不要只复制正在使用的主库。**

部署时将上面的备份命令放在现有Restic采集之前，要求成功后才执行后续备份，非零退出不能静默忽略。Restic保留一致性产物，排除活跃主库及WAL/SHM以免把非一致副本当成恢复依据。实际hook/cron、排除规则和时区在SRE仓库节点专属Restic配置中维护，**本PR不修改服务器或该仓库**，未接好前不得宣称已纳入一致性备份。

恢复先停API，在隔离目录恢复备份、检查user_version/quick_check/foreign_key_check及四项总量一致性；通过后再切换为live数据库，检查UID/GID，确认不存在混用的旧WAL/SHM，再启动。不能向运行中的live路径直接覆盖。从旧备份恢复可能丢失备份后的贡献，需记录恢复点，不能声称绝不回退。代码回滚保留data和备份，旧代码不会维护统计且可能重新展示瞬时评分；再次启用新版沿账本继续。

## 验证与发布边界

离线测试使用临时文件和内存论坛库，不访问开发者或生产数据。覆盖冻结/重入、源数回退、版本迁移、周期边界/重叠、溢出、事务与快照回滚、请求无SQL、含WAL一致性备份恢复、OpenAPI及三种模型。

上线需另行授权：准备目录权限/备份→部署→核对总量四项恒等式及R+E=T→多轮刷新/重启验证→独立复算推荐分。破坏性删除/重分类只用测试数据演练，不删除生产附件。首周期大增是存量入账，不做趋势解释。
