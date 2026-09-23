#!/usr/bin/env bash
# 海运费用归集与关税分摊系统 —— Linux / macOS 启动脚本（后端）
set -e
cd "$(dirname "$0")"

cd backend
if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 python3，请先安装 Python 3.11+"
  exit 1
fi

if [ ! -d venv ]; then
  echo "[1/3] 创建虚拟环境..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
echo "[2/3] 安装依赖..."
pip install -r requirements.txt

echo "[3/3] 启动服务（http://localhost:8000）..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
