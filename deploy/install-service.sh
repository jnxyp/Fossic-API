#!/bin/bash

set -e

# === 配置项 ===
SERVICE_NAME="fossic-api"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="/opt/Fossic-API"
VENV_DIR="$REPO_DIR/.venv"
PYTHON_BIN="python3.11"
SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME.service"
SYSTEMD_TARGET="/etc/systemd/system/$SERVICE_NAME.service"
APACHE_CONF_FILE="$SCRIPT_DIR/$SERVICE_NAME.conf"
APACHE_CONF_EXAMPLE="$SCRIPT_DIR/$SERVICE_NAME.conf.example"
APACHE_SITES_AVAILABLE="/etc/apache2/sites-available"
APACHE_SITES_ENABLED="/etc/apache2/sites-enabled"
APACHE_TARGET="$APACHE_SITES_AVAILABLE/$SERVICE_NAME.conf"

echo "📦 开始安装 Fossic API 服务..."

# === 检查是否为 root 用户 ===
if [ "$(id -u)" -ne 0 ]; then
  echo "❌ 请使用 root 权限运行本脚本，例如：sudo $0"
  exit 1
fi

# === 检查 Python 版本 ===
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "❌ 未找到 $PYTHON_BIN，请确保已安装 Python 3.11 或更高版本"
  exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
PYTHON_MAJOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
  echo "❌ 当前 Python 版本为 $PYTHON_VERSION，必须为 3.11 或更高版本"
  exit 1
fi

echo "✅ 已检测到 Python 版本：$PYTHON_VERSION"

# === 创建虚拟环境并安装依赖 ===
echo "🐍 创建虚拟环境：$VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo "📦 安装依赖项(requirements.txt)..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$REPO_DIR/requirements.txt"
deactivate

# === 安装 systemd 服务文件 ===
echo "🔗 创建 systemd 服务软链接..."
rm -f "$SYSTEMD_TARGET"
ln -s "$SERVICE_FILE" "$SYSTEMD_TARGET"

echo "🔄 重新加载 systemd..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
echo "✅ Fossic API 服务已启动"

# === 检查 Apache 并配置虚拟主机 ===
if command -v apache2 >/dev/null 2>&1; then
  echo "🌐 检测到 Apache，正在配置虚拟主机..."

  # 启用反向代理模块
  a2enmod proxy proxy_http

  # 幂等复制 Apache 配置文件
  if [ -f "$APACHE_CONF_FILE" ]; then
    echo "ℹ️ 发现已有 Apache 配置文件，跳过复制：$APACHE_CONF_FILE"
  else
    echo "📄 复制 Apache 配置文件..."
    cp "$APACHE_CONF_EXAMPLE" "$APACHE_CONF_FILE"
  fi

  # 创建软链接
  rm -f "$APACHE_TARGET"
  ln -s "$APACHE_CONF_FILE" "$APACHE_TARGET"

  # 启用站点
  a2ensite "$SERVICE_NAME.conf"

  echo "🔄 重新加载 Apache..."
  systemctl reload apache2

  echo "✅ Apache 虚拟主机已启用：http://api.fossic.org"
else
  echo "⚠️ 未检测到 Apache (apache2 命令），跳过虚拟主机配置"
fi

echo "🎉 安装完成！"
