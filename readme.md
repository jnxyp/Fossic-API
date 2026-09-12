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
3. 如需连接服务器，先读运维仓库 `cn-hk-fossic.md`；只使用 SSH 别名 `cn-hk-fossic`。MySQL 无宿主机端口映射，旧的 `localhost:3306` 转发方式已不适用。不要为本地测试开放线上端口。
4. 从仓库根目录启动服务
```bash
python -X utf8 -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000
```
5. 访问 http://localhost:8000/ 检查服务状态，http://localhost:8000/docs 查看API文档

Windows UTF-8 环境与离线测试步骤、`GET /mods` 发布元数据定义见 [发布元数据与本地验证](docs/mod-releases.md)。
