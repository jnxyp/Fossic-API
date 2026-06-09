# Code Review — 2026-06-08

## 状态总览

| # | 文件 | 行号 | 严重程度 | 问题简述 | 状态 |
|---|------|------|----------|----------|------|
| 1 | `src/dao.py` | 182 | 🔴 崩溃 | `KeyError: 'mod_info_type'`（纯管理员备注帖） | ✅ 已修复 |
| 2 | `src/dao.py` | 187 | 🔴 崩溃 | 缺少 `modAuthor`/`modVersion` 行时 `ValidationError` | ✅ 已修复 |
| 3 | `src/tables.py` | 35 | 🔴 崩溃 | `split('=')` 缺少 `maxsplit=1`，值含 `=` 时崩溃 | ✅ 已修复 |
| 4 | `src/dao.py` | 166 | 🔴 崩溃 | `mod_safe_rm[value]` 无键检查，异常被静默吞掉 | ✅ 已修复 |
| 5 | `src/cache.py` | 29 | 🟠 并发 | 刷新时无锁，读写竞态导致缓存状态不一致 | ✅ 已修复 |
| 6 | `src/main.py` | 27 | 🟠 启动 | `async lifespan` 内直接调用同步阻塞 I/O | ✅ 已修复 |
| 7 | `src/utils.py` | 11 | 🟡 数据 | 无时区 `datetime` 导致时间戳在 UTC+8 偏差 8 小时 | ✅ 已修复 |
| 8 | `src/api.py` | 11 | 🟠 缓存 | HTTP 响应缓存不随 `ModCache.refresh()` 失效，最大过期 600s | ✅ 已修复 |
| 9 | `src/dao.py` | 111 | 🟡 质量 | `set` 直接赋值给 `List[str]` 字段，顺序不确定 | ✅ 已修复 |
| 10 | `src/dao.py` | 162 | ⚪ 清理 | 死代码，含潜在无 guard 的 `KeyError` | ✅ 已修复 |

---

## 详细说明

### #1 `src/dao.py:182` — KeyError: 'mod_info_type' 🔴

**问题**：`modIndexComment`（第 81 行）和 `adminThreadComment`（第 84 行）两个分支均在设置 `mod_info_type`（第 88 行）之前 `continue`。若某帖子的所有 `typeoptionvar` 行都是这两种 identifier，`mod_info_type` 键永远不会写入 `info` 字典，第 182 行 `info["mod_info_type"]` 直接抛 `KeyError`，整次 `get_all_mods()` 崩溃。

**修复方向**：在第 181 行的 `if not "mod_id" in info` 检查附近，同样跳过没有 `mod_info_type` 的帖子，并记录 warning。

---

### #2 `src/dao.py:187` — ValidationError（必填字段缺失）🔴

**问题**：`ModInfo` 中 `mod_author_names: List[str]` 和 `mod_game_versions: List[str]` 没有默认值。这两个键只在遇到对应 identifier 时通过 `setdefault` 写入，若帖子缺少 `modAuthor` 或 `modVersion` 行，`ModInfoOriginal(**info)` 抛 `ValidationError`，缓存刷新中止。

**修复方向**：在模型中给这两个字段加默认值 `= []`，或在构造前对 `info` 补全缺省值。

---

### #3 `src/tables.py:35` — split('=') 缺少 maxsplit 🔴

**问题**：`key, value = row.split('=')` 对含 `=` 的值（如 URL 参数、Base64）会产生 3 个以上元素，解包报 `ValueError: too many values to unpack`，导致所有选项查询（游戏版本、语言、依赖等）全部崩溃。

**修复**：`row.split('=', 1)` 一行即可修复。

---

### #4 `src/dao.py:166` — mod_safe_rm[value] 无 guard 🔴

**问题**：管理员若删除了"是否可安全移除"的某个选项，旧帖子的 `typeoptionvar` 仍保留旧 key，`mod_safe_rm[value]` 直接 `KeyError`。该异常被 `cache.py:43` 的 `except Exception` 静默吞掉，缓存停留在旧数据，无任何明显报错。

**修复方向**：改为 `mod_safe_rm.get(value, "否") == "是"`，或在 warning 后跳过该字段。

---

### #5 `src/cache.py:29` — 无锁并发写 🟠

**问题**：`refresh()` 对 `_game_versions`、`_mod_languages`、`_mod_categories`、`_mod_dependencies`、`_mods` 是五次独立赋值，无任何锁保护。APScheduler 后台线程刷新中途，FastAPI 请求线程可能读到新旧混合的中间状态。

**修复方向**：用 `threading.Lock`，刷新时先构造新数据，再原子性地替换所有字段；或将五个字段打包为单个对象一次性赋值。

---

### #6 `src/main.py:27` — async lifespan 内同步阻塞 I/O 🟠

**问题**：`lifespan` 是 `async def`，但 `refresh_cache()` → `mod_cache.refresh()` 执行同步 SQLAlchemy 查询，阻塞整个 asyncio 事件循环，启动期间服务无法响应任何请求。

**修复方向**：
```python
await asyncio.get_event_loop().run_in_executor(None, mod_cache.refresh)
```

---

### #7 `src/utils.py:11` — 无时区时间戳偏差 8 小时 🟡

**问题**：`datetime.strptime` 返回 naive datetime，`.timestamp()` 按服务器本地时区（香港 UTC+8）换算。`2024-01-01` 返回的 Unix 时间戳比 UTC 午夜早 28800 秒（8 小时），客户端按日期过滤 `mod_update_date` 会出现偏差。

**修复**：
```python
from datetime import datetime, timezone
dt = datetime.strptime(date_string, '%Y-%m-%d').replace(tzinfo=timezone.utc)
return int(dt.timestamp())
```

---

### #8 `src/api.py:11` — HTTP 缓存不随 ModCache 刷新失效 🟠

**问题**：`ModCache` 每 300s 刷新一次内存数据，但 `fastapi-cache2` 的 HTTP 响应缓存（同为 300s）不会被主动清除。客户端实际可能拿到最多 **600s** 前的旧数据。

**修复方向**：在 `refresh_cache()` 成功后调用 `FastAPICache.clear()`（需在异步上下文中调用，可用 `asyncio.run_coroutine_threadsafe`）。

---

### #9 `src/dao.py:111` — set 赋值给 List[str] 字段 🟡

**问题**：`mod_author_names`、`mod_game_versions`、`mod_dependency_names`、`mod_conflict_names`、`mod_translator_names` 均以 `set` 形式构建后直接传入模型，Pydantic 虽能强制转换，但 `set` 迭代顺序不稳定，API 响应中这些列表的顺序每次刷新后可能不同。

**修复**：构造模型前将各 `set` 转为 `sorted(...)` 列表。

---

### #10 `src/dao.py:162` — 死代码含潜在 KeyError ⚪

**问题**：第 150–157 行已处理 `identifier == "modVersion"` 并 `continue`，第 162–163 行同名分支永远不会执行。且该死代码中 `game_versions[value]` 没有像第 154 行那样先做 `if version in game_versions` 检查，若将来误删上方 `continue` 会立即 `KeyError`。

**修复**：直接删除第 162–163 行。
