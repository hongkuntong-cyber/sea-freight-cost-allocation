#!/usr/bin/env bash
# Linux / macOS 本地试用：首次运行需要 Python 3.11+、Node.js 22+ 和联网安装依赖。
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "请先安装 Python 3.11 或更新版本"
  exit 1
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
  echo "请先安装 Python 3.11 或更新版本"
  exit 1
}

if [ ! -f frontend/dist/index.html ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "请先安装 Node.js 24 LTS（或 22 LTS），用于首次构建网页界面"
    exit 1
  fi
  echo "[1/3] 构建网页界面..."
  npm ci --prefix frontend
  npm run build --prefix frontend
fi

if [ ! -x backend/venv/bin/python ]; then
  echo "[2/3] 创建 Python 虚拟环境..."
  python3 -m venv backend/venv
fi
echo "[2/3] 安装后端依赖..."
backend/venv/bin/python -m pip install -r requirements.txt

echo "[3/3] 服务启动后，在浏览器打开 http://127.0.0.1:8000"
echo "数据保存在本机 backend/data 目录。按 Ctrl+C 停止服务。"
cd backend
venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
