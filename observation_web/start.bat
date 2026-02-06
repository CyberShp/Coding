@echo off
REM ============================================================
REM Observation Web Advance - Windows 一键启动脚本
REM 同时启动后端 (FastAPI) 和前端 (Vite Dev Server)
REM ============================================================

echo =====================================
echo   Observation Web Advance 启动中...
echo =====================================

REM Check Python
where python3 >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set PYTHON_CMD=python3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set PYTHON_CMD=python
    ) else (
        echo 错误: 未找到 Python，请先安装 Python 3.8+
        pause
        exit /b 1
    )
)

REM Install backend dependencies
%PYTHON_CMD% -c "import fastapi" 2>nul
if %ERRORLEVEL% neq 0 (
    echo 安装后端依赖...
    %PYTHON_CMD% -m pip install -r requirements.txt -q
)

REM Install frontend dependencies
if not exist "frontend\node_modules" (
    echo 安装前端依赖...
    cd frontend && npm install && cd ..
)

echo 启动后端服务...
start "Backend" %PYTHON_CMD% -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

echo 启动前端服务...
cd frontend
start "Frontend" npm run dev
cd ..

echo.
echo =====================================
echo   服务已启动!
echo   后端 API: http://localhost:8000
echo   前端界面: http://localhost:5173
echo   API 文档: http://localhost:8000/docs
echo =====================================
echo.
echo 关闭此窗口不会停止服务
echo 请手动关闭 Backend 和 Frontend 窗口来停止服务

pause
