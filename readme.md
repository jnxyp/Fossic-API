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
2. 将.env.example 重命名为 .env，并填充入数据库连接信息
3. 端口映射到Fossic.org的数据库（或者使用本地数据库）
```bash
ssh -Nf -L 3306:localhost:3306 fossic
```
4. 启动服务
```bash
uvicorn src/main:app --reload --host
```
5. 访问 http://localhost:8000/ 检查服务状态，http://localhost:8000/docs 查看API文档