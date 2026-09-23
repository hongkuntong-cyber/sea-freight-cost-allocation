@echo off
REM 海运费用归集与关税分摊系统 —— Windows 一键启动（仅后端 API + 内置前端托管）
REM 前置：已安装 Python 3.11+ 与 Node.js 18+（若要构建前端界面）。
setlocal

cd /d "%~dp0"

REM 1) 安装并启动后端
cd backend
where python >nul 2>nul
if %errorlevel%==0 (set PY=python) else (set PY=py)

if not exist venv (
  echo [1/3] 创建 Python 虚拟环境...
  %PY% -m venv venv
)
call venv\Scripts\activate
echo [2/3] 安装后端依赖...
pip install -r requirements.txt

echo [3/3] 启动服务（http://localhost:8000）...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
endlocal
