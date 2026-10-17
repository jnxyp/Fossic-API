# 游戏发布 API

`GET /games` 返回游戏发布分类（sortid=9、当前公开版块 fid=39）的帖子列表，按 tid 倒序。字段风格与 `/mods` 一致，复用 `thread_meta`，不从文件名推测版本或平台。

- 顶层：`game_release_name`、`game_release_version`、`game_author_names`、`game_allow_direct_download`、`game_publish_urls`、`game_releases`、`thread_meta`。
- 作者来自 `gameReleaseAuthor`，按英文逗号拆分、去空白，与 Starsector 四位原作者合并后去重、排序；缺失或留空仍返回四位原作者。直链开关来自 `gameAllowDirectDownload` 的 choices，仅选项标签“是”为 true，缺失/异常为 false。
- `game_release_name` / `game_release_version` 分别读取 gameReleaseName / gameReleaseVersion，去除首尾空白，缺失或空白为 null，不从标题或附件猜测。帖子标题移至共享 `thread_meta.title`，Mod API 也返回真实论坛标题；移除原顶层 game_title。附件中的 game_version / release_version 保持原语义。
- 每项发布：`attachment_id`、`is_full_game`、`game_version`、`platform`、`language`、`package_type`、`release_version`、`display_name`，以及与 Mod 相同的 `download_count`、`file_name`、`file_size`、`uploaded_at`、`download_url`。
- `game_version` 为保存的版本文字（如 `0.98`）；`release_version` 保留 `v` 等作者文字。平台 windows/macos/linux/universal，语言 zh-Hans/zh-Hant/en/other，包类型 zip/self_extracting/other。空备注为 null，数组顺序保留。
- JSON 解析先尝试原文，失败时只解码一层 Discuz 特殊字符实体。最多200项，非法条目和重复 aid 局部过滤；字段缺失/坏 JSON 为 null，显式空数组为 []。日志只记录 tid 和数量。
- 附件元数据与 Mod 复用同一批查函数：索引 tableid 决定真实分表，每批最多500项；跨帖、图片、缺失/非法明细不生成文件信息或 URL，不探测 COS/CDN。

直链开启且附件明细有效时，链接为 `https://www.fossic.org/forum.php?mod=misc&action=gamedownload&aid=<ID>`。入口即时核验游戏分类、附件/帖子归属、发布登记及作者开关，再进入原生附件下载流程，由原生流程执行权限和计数；开关关闭则跳回帖子。API 缓存中的旧链接不能绕过新关闭的开关。返回链接不代表任意访客都有下载权限。

## 缓存与验证

游戏使用独立的内存快照，沿用现有刷新周期（默认300秒）和接口缓存。请求不查库，刷新失败保留旧快照；任一快照更新时清除接口缓存。`/status` 增加 `game_cache`，原 `cache` 保留 Mod 含义。API 查询不需要新增数据库权限；论坛分类字段绑定还必须完成对应 optionvalue 表的列和索引迁移。

在仓库根运行 `.venv/Scripts/python.exe -X utf8 -m pytest -q`。本轮104项通过，涵盖 SQLite 分表、公开范围、字段/开关、坏数据、缓存失败保留及接口契约；论坛另有53项 Mod/游戏下载入口测试。

上线前同一线上只读事务对比784个 Mod，新旧返回完全一致；游戏帖19430的16项均有完整元数据，作者未填写、直链开关未设置，保持 []/false、所有 download_url=null。正向开放分支使用隔离测试验证，不为验收自动改变公开帖开关。

## 部署与回滚

先部署论坛下载入口及已有字段45/46绑定，再 fast-forward API 并仅重启 `fossic-api` 服务。线上 `.env` 不覆盖。回滚 API 可恢复部署前代码；论坛分类模板和字段绑定先从本次 `data/deploy-backups/game-api-before-*.json` 核对恢复，更新 threadsorts 缓存。不得删除或覆盖用户后来填写的分类字段值。


## 2026-10-17 UTC 上线结果

- 运行代码 `a221832`，论坛入口 `ccb65c9e` 已先上线。API 03:24:48 UTC 启动刷新成功，游戏1帖/16项、Mod784项；公网 `/games` 200、MISS→HIT，OpenAPI 和 `/status.game_cache` 正常，游戏版本接口保持20项。
- 论坛字段45/46已绑定分类9，模板核对后更新，备份为 `data/deploy-backups/game-api-before-20261017.json`。19430作者/开关未补写，16项 JSON 未变，全部 download_url=null。匿名 HTTP（明确客户端 UA）和登录 Chrome 均验证关闭开关时302回原帖。
- Chrome 桌面及Android触屏编辑页均有原生作者/开关控件、16项正确回显；开关未自动选“是”，390px无横向溢出，未保存帖子。PHP worker 对缓存目录创建/覆盖/删除测试成功，部署文件1000:1000、备份0600。
- Loki 上线观察窗口确认 GameCache 刷新成功，未见 API ERROR/CRITICAL。自动化104项 API 和53项论坛入口测试通过；没有开启公开帖直链或下载大型安装包，开放分支及最终权限交接由隔离回归测试验证。


### 分类保存修复

首次部署遗漏论坛后台绑定字段时对应的 optionvalue 表迁移，用户编辑开关报1054。2026-10-17 UTC按原生定义补齐分类9的 gameAllowDirectDownload 列/索引及 gameReleaseAuthor 列，迁移见论坛 `migrations/2026-10-17-game-release-optionvalue.sql`（论坛提交f373e4b4）。用户失败提交已保存开关1、作者远星汉化组；保留这些值并实际浏览器提交成功，16项及正文未改变。03:34:51 UTC定时刷新后 `/games` 返回作者[远星汉化组]、允许直链true、16个稳定下载链接；实际入口302原生attachment，未下载大型文件。分类表结构必须在启用控件前核验，隔离下载测试不能替代原生发帖保存验收。


### 游戏语言细分

运行代码80f8e70：语言枚举统一为zh-Hans/zh-Hant/en/other，旧zh不再接受，Mod语言字段不变。论坛同步编辑器、帖子卡片、下载入口及线上插件生效配置；19430全部16项语言迁移为zh-Hans。109项API回归通过；公网16项、16个下载链接及OpenAPI语言枚举验证通过，作者和开关保留。


## 游戏原作者与帖子字段（2026-10-16 PDT）

原作者名单来源于本机游戏0.98a-RC8制作人员页面的 `starsector-core/starfarer_obf.jar!com/fs/starfarer/title/A/oOOO.class`：Alex Mosolov（开发、游戏设计主管）、David Baumgart（艺术、游戏设计、写作、编程）、Stian Stark（音乐、音频设计）、Ivaylo Kovatchev（写作、游戏设计、编程）。QA特别鸣谢及汉化署名不自动追加；汉化作者来自论坛填写值。使用游戏页面上的Alex署名，不另外添加Alexander别名。

只在只读DAO组装游戏快照时合并原作者，不写回数据库或改变编辑控件。两个新字段沿用已有字段查询/快照/接口缓存；请求不查库。模型共享的thread_meta.title直接取forum_thread.subject，保持标题原文，Mod名称字段不变。已检查现有索引前端与论坛静态脚本，无game_title调用方。外部客户端需由game_title迁移至thread_meta.title。

实施验证覆盖填写/空白/缺失字段、填写作者重复及与原作者重复、游戏与Mod标题、OpenAPI、缓存MISS/HIT及无接口查库；沿用附件、开关、坏数据与刷新失败保留回归。回滚点06465eb；恢复旧代码后重启API即可恢复旧响应，论坛数据未修改。
