@echo off
chcp 65001 >nul
REM Windows 本地试用：首次运行需要 Python 3.11+、Node.js 22+ 和联网安装依赖。
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 goto :no_python
  set "PY=python"
)
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 goto :no_python

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 goto :no_node
  echo [1/3] 构建网页界面...
  pushd frontend
  call npm ci
  if errorlevel 1 goto :failed
  call npm run build
  if errorlevel 1 goto :failed
  popd
) else (
  echo [1/3] 使用已有网页界面。
)

if not exist "backend\venv\Scripts\python.exe" (
  echo [2/3] 创建 Python 虚拟环境...
  %PY% -m venv "backend\venv"
  if errorlevel 1 goto :failed
)
echo [2/3] 安装后端依赖...
"backend\venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto :failed

echo [3/3] 服务启动后，在浏览器打开 http://127.0.0.1:8000
echo 关闭此窗口即可停止服务；数据保存在本机 backend\data 目录。
pushd backend
"venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto :failed
popd
exit /b 0

:no_python
echo 请安装 Python 3.11 或更新版本，安装时勾选 Add python.exe to PATH。
goto :failed

:no_node
echo 请安装 Node.js 24 LTS（或 22 LTS），用于首次构建网页界面。
goto :failed

:failed
echo 启动未完成，请查看上方报错信息。
pause
exit /b 1
