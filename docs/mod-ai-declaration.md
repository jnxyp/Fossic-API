# Mod 生成式 AI 声明

本变更仅提交API代码与测试，尚未部署。跟踪：issue #6。分页不在本次范围。

## 公开协议

`GET /mods` 与 `GET /mods?include_modding=true` 的原创、汉化、转载对象统一增加 `mod_ai_declaration`。声明由发布者自愿填写，是其对发布作品的已知情况说明，不是平台AI检测结果，也不代表质量评价。游戏接口不增加该字段。

```json
{
  "mod_ai_declaration": {
    "status": "yes",
    "code": "assisted",
    "art": "full",
    "audio": "none",
    "text": "none"
  }
}
```

| 字段 | 可取值 |
|---|---|
| status | undeclared 未声明 / yes 使用 / no 未使用 |
| code、art、audio、text | undeclared 未声明 / none 未使用 / assisted 辅助创作 / full 完全使用 |

三个状态的组合规则：

- `undeclared`：四维全部为undeclared，不能推断任何一维未使用。
- `no`：四维全部none。
- `yes`：四维只能为none/assisted/full，至少一维不是none。

模型五键均必需、拒绝额外键；包含三个状态与枚举的OpenAPI由 `ModAiDeclaration` 生成，跨字段组合由模型验证器检查（OpenAPI枚举本身不完整表达所有组合约束）。基础Mod模型使用工厂创建独立默认对象，避免不同帖子共享可变声明。

## 论坛输入与API输出的区别

论坛已有字段标识 `modAiDeclaration`，从现有 `forum_typeoption` / `forum_typeoptionvar` EAV JOIN读取。按identifier识别，不能硬编码optionid。**API不修改论坛存储、编辑器或校验规则。**

论坛合法未声明原值：

```json
{"status":"undeclared","code":"none","art":"none","audio":"none","text":"none"}
```

API规范化为：

```json
{"status":"undeclared","code":"undeclared","art":"undeclared","audio":"undeclared","text":"undeclared"}
```

必须先验证源JSON的五键和组合，再规范化；源数据undeclared+full等矛盾组合不能被当作有效输入。API四维的undeclared不是论坛允许存储的枚举值。

无EAV记录、null输入、空白、格式损坏、未知枚举、残缺/额外字段、矛盾组合、重复键、非标准JSON常量、超限/坏Unicode、非公开或过期字段均返回API五项undeclared。不要把异常/空值映射为no，也不回显原文或返回质量认证标签。非空错误只记录tid和异常类别，不写入原始JSON、HTML或Pydantic错误详情。

### 解码与边界

`parse_mod_ai_declaration` 使用与PHP `htmlspecialchars_decode(..., ENT_QUOTES)`一致的特殊实体映射解码一次，再检查2048 UTF-8字节上限及JSON结构。不会泛化解码其他HTML实体，不重复解码，不去除反斜杠或渲染HTML。允许普通原始JSON和被论坛转义一次的JSON，双重转义不自动修复。

JSON对象必须恰好五个键；yes的四维组合保留，不推断其他维度。解析失败保守回退只影响本条声明，不会使整个Mod快照失败。

### 公开与过期策略

沿用API原有帖子可见范围，仅接受该帖当前sortid/fid对应的声明EAV行。`ForumTypeOption`只读映射补充论坛已有protect、expiration两列，没有DDL或新权限。

公开投影保守处理：空protect或明确status关闭且未配置用户组/认证限制的protect可以公开；保护开启、受限、未知或损坏配置不公开，不模拟登录用户/作者权限。此策略可以比论坛对特定用户的访问更严格，但不会为API访客放宽访问。

过期检查遵循原生字段expiration开关；只有字段启用过期、EAV期限非零且不晚于本轮now时才视为过期。权限/期限变更跟随下一次缓存刷新，不在每个请求查库。未修改其他字段的过滤策略。

## 数据流及兼容性

`ModDAO.get_all_mods()` 在原查询结果的identifier分派中解析，无逐帖SQL；一个刷新轮次使用同一个声明过期检查时间。三种模型、Modding与默认视图使用同一声明对象的规范化数据。

SnapshotCache现有验证、推荐分计算、统计事务和预编码链不变。访客请求直接返回bytes，不访问论坛/统计库、不调用声明解析器、不重编码模型。更新原始声明需要下一次成功刷新才可见。下载总数、excluded、内部版本统计、推荐分及列表顺序不受影响，`mod_download_counts_by_game_version`仍不公开。

旧客户端可忽略新增对象；API未新增路由，/games不变。无论坛数据库迁移、SQLite迁移、依赖、环境变量、独立调度或前端变更。

## 测试与发布

`tests/test_mod_ai_declaration.py` 覆盖80种有效yes组合与全none矛盾组合、三种状态、四个维度、一次实体解码、UTF-8字节限制、坏输入、脱敏日志、保护/过期/错位EAV、三类Mod及Modding、查询次数、默认值对象隔离、源修改的缓存可见性、坏声明不影响统计、OpenAPI及热路径无SQL/解析/编码。

离线测试必须使用隔离数据库与临时DOWNLOAD_STATS_DB_PATH；Windows pytest使用独立basetemp避免既有临时目录权限冲突。从仓库根目录运行：

```powershell
$env:PYTHONUTF8='1'
$testTemp=Join-Path $env:TEMP ('fossic-ai-'+[guid]::NewGuid().ToString('N'))
./.venv/Scripts/python.exe -X utf8 -m pytest -q --basetemp=$testTemp
```

合并/部署另行授权。仅源码变化时按节点部署手册更新并重启API，保留数据库和备份配置；上线后核对三种类型、默认/完整视图、真实声明与未声明输出、OpenAPI、快照健康和下载对账。回滚代码无需修改论坛字段或清理统计数据。
