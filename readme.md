# Fossic API

Fossic.org 的独立 API 接口实现，因为实在改不动原来的 Discuz 大💩山了，然后也懒得学PHP。

## 系统要求
- Python 3.11+

如要使用deploy目录下的自动安装脚本，则还需要
- linux/ubuntu 系统
- systemd 支持
- apache2 作为反向代理

## 本地运行
1. 创建虚拟环境并安装依赖
```bash
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```
2. 复制 `.env.sample` 为 `.env`，填写本地或只读数据库连接信息。不要覆盖已有 `.env`。
3. 如需连接服务器，先读运维仓库 `cn-hk-fossic/README.md`；只使用 SSH 别名 `cn-hk-fossic`。MySQL 无宿主机端口映射，旧的 `localhost:3306` 转发方式已不适用。不要为本地测试开放线上端口。
4. 首次启动前创建统计目录 `data/`（或 DOWNLOAD_STATS_DB_PATH 指定文件的父目录），确保服务用户可写。SQLite 是业务统计，不是可删除重建的缓存；部署权限、备份和恢复要求见 [持久下载统计](docs/download-statistics.md)。
5. 从仓库根目录启动服务
```bash
python -X utf8 -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000
```
6. 访问 http://localhost:8000/ 检查服务状态，http://localhost:8000/docs 查看API文档

Windows UTF-8 环境与离线测试步骤、`GET /mods` 发布元数据定义见 [发布元数据与本地验证](docs/mod-releases.md)。

游戏下载字段、缓存及部署验证见 [游戏发布 API](docs/game-releases.md)。

Mod 综合推荐评分字段、所有版本下载口径及前端消费约定见 [综合推荐分](docs/mod-recommendation.md)。

Mod 总下载数、已排除下载数、分游戏版本累计量和周期存储见 [持久下载统计](docs/download-statistics.md)。本次变更仅提交代码，尚未部署；历史部署日志不代表新增 /data 挂载已上线。


Mod 生成式 AI 声明的字段、未声明规范化及公开边界见 [AI 声明协议](docs/mod-ai-declaration.md)。

## 缓存和状态接口

统一的SnapshotCache管理Mod、游戏及元数据响应。每次后台刷新完成数据库读取、校验和JSON编码；Mod 还需成功提交持久下载统计事务，再原子替换该类别的完整快照；请求直接返回已编码的bytes，不查库、不重新过滤列表、不重新序列化。默认Mod列表和含Modding列表是同一份刷新数据的两个预生成视图。内存只保留响应字节和数量/时间，不再保留一份重复的业务模型列表。

唯一刷新周期仍使用MOD_CACHE_TIME（默认300秒，名称沿用部署兼容），同时控制Mod和游戏。移除API_CACHE_TIME及fastapi-cache2；没有第二套TTL、MISS/HIT或清理响应缓存步骤，旧X-FastAPI-Cache/ETag相关行为不再提供。模型response_model继续用于OpenAPI，刷新阶段确保业务模型有效。无需新增Redis。

Mod与游戏分别提交成功快照；任一类别查库或编码失败保留该类别全部旧响应及时间戳，另一类可正常更新。刷新串行执行，已有APScheduler max_instances=1/coalesce保留，请求不持有查库/编码期间的锁。

GET /status只在cache下返回缓存状态：

```json
{
  "status": "ok",
  "docs_url": "https://api.fossic.org/docs",
  "cache": {
    "status": "ok",
    "refresh_interval_seconds": 300,
    "mods": {"status": "ok", "count": 784, "last_updated": 1792210415, "last_updated_iso": "2026-10-17T04:13:35+00:00"},
    "games": {"status": "ok", "count": 1, "last_updated": 1792210415, "last_updated_iso": "2026-10-17T04:13:35+00:00"}
  }
}
```

count是含Modding的Mod总数或游戏帖数。各类别最后成功刷新时间独立，未初始化时间为-1/ISO为null；超过刷新周期两倍为expired，任一类别过期则cache.status为expired。顶层status沿用服务在线含义。原顶层game_cache及cache.mod_count/last_updated迁移至cache.games/cache.mods；客户端需按新结构读取。

本地验证：.venv/Scripts/python.exe -X utf8 -m pytest -q，覆盖默认/完整列表、所有模型字段、元数据、请求无SQL/编码、原子提交、编码和附件查询失败保留旧数据、部分过期状态。上线需重建仅API镜像以移除旧依赖，保留旧镜像和.env备份用于回滚；不改论坛数据。


2026-10-16 PDT部署：运行b5ffe69，119项本地回归通过。生产只读事务对比全部六种响应与DAO模型JSON完全相同（784个Mod、1个游戏）；新镜像同样通过此验证且fastapi_cache模块不存在。公网默认481个Mod、含Modding784个、游戏16个附件/直链，所有接口重复请求字节一致、默认和显式false一致、OpenAPI及集中/status正常。只重建API容器，json-file轮转20m×3、仅src bind mount，无匿名卷。

首次Compose构建因构建桥接网络DNS解析失败，改用docker build --network=host构建成功；运行网络未改变。旧镜像保留为fossic-api-fossic-api:before-cache-unification-89fb965；原.env备份位于相邻FossicDiscuz/data/deploy-backups/api-env-before-cache-unification-89fb965.env（0600、1000:1000、既有Restic范围），只移除废弃API_CACHE_TIME，其余变量原样保留。回滚须同时恢复Git 89fb965、旧.env及旧镜像标签，再仅重建API容器；旧代码依赖fastapi-cache2，不能直接搭配新镜像运行。


安全加固改动、兼容边界与本地验证见 [2026-10-21 安全修复（待审核，未部署）](docs/security-2026-10-21.md)。
