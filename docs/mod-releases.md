# Mod 发布元数据

`GET /mods` 为每个 Mod 增加 `mod_releases` 和 `mod_allow_direct_download`，其余字段含义不变。默认板块仍是 46/60/78，`include_modding=true` 额外包含 71。DAO 的 sortid、displayorder 等过滤保持原样。顶层 `mod_version` 仍来自 `modReleaseVersion`，不从发布数组推算最新版本。

示例（游戏版本选项以数据库当前定义为准）：

```json
{
  "mod_version": "1.2.0",
  "mod_releases": [
    {
      "attachment_id": 12345,
      "game_version_id": "modVersion_098x",
      "game_version": "0.98",
      "mod_version": "1.2.0",
      "display_name": "稳定版 1.2.0",
      "download_count": 620
    }
  ],
  "mod_allow_direct_download": true
}
```

## 解析约定

- `modReleaseFilesMapping` 先解析普通 JSON；失败时按论坛保存方式解码一层 HTML 特殊字符实体再解析，避免破坏普通 JSON 字符串内的字面量实体。缺失、空白、非法 JSON 或非数组返回 `null`；解析失败记录帖子 ID，不记录原始内容。
- 明确的 `[]` 或数组条目全部被过滤，返回 `[]`。
- 保留作者顺序，不排序、不合并同版本附件、不去重。开关为 false 时仍返回发布元数据。
- `aid` 接受正整数或仅含 ASCII 数字的字符串，并须处于 Discuz 无符号 INT 范围；拒绝布尔值、浮点数、零和负数。解析阶段仅验证格式；计数补查阶段校验附件索引记录存在及所属帖子，不验证文件实际可下载性或访问者下载权限。
- `gameVersion` 必须是规范选项 ID 字符串，精确匹配 `ForumTypeOption.get_game_versions()`；显示文字只取规范选项。忽略保存的 `gameVersionDisplayValue`，未匹配则丢弃整个条目。
- `modVersion` 必须是非空字符串，去除首尾空白。`modVersionDisplayName` 可缺失、为 null 或空白，统一返回 `display_name: null`；非字符串为无效条目。无法 UTF-8 序列化的条目也被过滤。
- 无效条目局部过滤，日志汇总帖子 ID 和过滤数量，不影响同帖有效条目或整批缓存刷新。
- `modAllowDirectDownload` 根据该字段数据库 rules 中的 choices 解析，仅匹配标签“是”返回 true；缺失、空白、未知值、无效 choices 均为 false。2026-09-12 只读核实：optionid=42，radio，`1=是`、`2=否`；字符串 `0` 为 false。

不返回下载 URL 或附件详情。`mod_allow_direct_download` 表示作者字段设置，不代替论坛授权；签名链接不在本次范围内。

ModCache 和接口响应缓存默认各为 300 秒；既有后台刷新成功后清理响应缓存的流程保持不变。修改论坛字段后需等待缓存更新。

## 排序统计扩展（本地实现，尚未部署）

`thread_meta` 新增 `heats`（累计参与热度）和 `views`（已落库累计浏览量）；`mod_releases` 的每一项新增 `download_count: int | null`。既有字段、版本映射和默认板块过滤不变，OpenAPI 自动包含新字段。

热度、浏览量直接来自已有帖子关联查询；下载量在缓存刷新时对有效 Mod 的附件 ID 去重，每批最多 500 个，按 `pre_forum_attachment.aid` 主键查 aid/tid/downloads。无 Release 时不查附件表。该表须允许 API 账号 SELECT；不创建或修改论坛数据库表。

附件索引记录缺失、跨帖引用或负计数时，仅该项返回 null；其他项仍保留有效计数。数据库查询失败则使本轮刷新失败，保留旧缓存，不能伪装成所有附件缺失。计数为 0 是有效数据。文件或远端对象已丢失但数据库记录仍在的情况，无法通过该查询识别；不额外请求存储服务探测。

消费端按筛选后显示的最高匹配游戏版本，选出对应 Release，以 attachment_id 去重并对非 null 计数求和；逐个跳过无效附件，不连带影响其他项。全无有效项才视为无数据并排后。本 API 不接受排序参数、不预先跨游戏版本合计，也不合并或删除原映射项。

本次验证：48 项 SQLite / TestClient 测试通过，覆盖热度与浏览量、有效及零计数、删除附件、跨帖引用、负计数、重复 ID、500/501 批次边界、无映射零查询、刷新失败保留旧快照、MISS/HIT 及刷新后的统计、OpenAPI 字段。未连接生产数据库，未核实生产账号附件权限或 MySQL EXPLAIN；生产性能及权限核对仍为部署前步骤。

## Windows 本地运行和测试步骤

在仓库根目录执行（Python 3.11+）：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
python -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

若使用 uv，可用 `uv venv .venv --python 3.11` 和 `uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt`。

测试使用内存 SQLite 和 FastAPI TestClient，不访问线上数据库，不需要 `.env` 或启动监听端口。测试启动前覆盖数据库环境变量为本地无效地址，防止意外读取开发者连接配置。覆盖解析边界、三个 Mod 模型、真实 SQL join 和过滤、两级缓存、响应缓存命中及刷新失效。

实际启动 API 时，复制 `.env.sample` 为 `.env` 并配置可访问的数据库（保留已有文件），执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000
```

服务启动会查询数据库并定时刷新本地缓存。使用本地数据库或经授权的只读账号；服务器连接须先阅读运维仓库对应文档，并使用 SSH 别名。结束后 Ctrl+C 关闭服务及临时隧道。

## 本次验证记录（2026-09-12）

44 项离线测试通过，包含普通及 HTML 转义 JSON 中字面量实体的回归测试；依赖 Starlette 的 TestClient 有一条 AnyIO 弃用提示，不影响结果。

经 `ssh cn-hk-fossic`，在现有 API 容器内复用只读账号 `fossicor_starsector_api`，执行只读事务 SELECT，抽取 16 帖、356 条分类字段和 34 项字段定义，在本地内存 SQLite 中运行修改后的 DAO 和完整应用 TestClient。未输出凭据，未修改线上服务、数据、权限或缓存；未建立隧道或持久服务。

- 16 个有效 Mod；默认接口返回 13 个，include_modding=true 返回 16 个。
- 共 7 个发布条目，接受 7 个、过滤 0 个；9 帖明确为空数组，无缺失字段样本（缺失/脏数据由离线用例覆盖）。
- 13 帖允许直链。两种请求均验证 MISS/HIT，新字段一致。
- 使用同一数据运行修改前 HEAD 的 DAO，排除两个新增字段后逐项相等。
- 抽样不是全库审计，未检查附件存在性或实际下载能力。

额外发现既有联合模型缓存解析问题：汉化帖空的 `mod_translator_names` 在响应缓存 HIT 时可能缺失，已用修改前 HEAD 的模型单独复现。本次未调整联合类型，避免扩大行为变更；链路测试仅将该字段的缺失和空数组视为等价，其余字段逐项比较，新发布字段不受影响。
