@echo off
REM NPM 离线包准备脚本 (Windows)
REM 在联网环境运行此脚本，下载所有 npm 依赖

setlocal enabledelayedexpansion

echo === NPM 离线包准备脚本 ===

REM 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"
set "FRONTEND_DIR=%SCRIPT_DIR%..\..\frontend"

echo 前端目录: %FRONTEND_DIR%
echo 输出目录: %SCRIPT_DIR%
echo.

REM 检查 npm
where npm >nul 2>&1
if errorlevel 1 (
    echo 错误: npm 未安装
    exit /b 1
)

REM 进入前端目录
cd /d "%FRONTEND_DIR%"

REM 确保有 package-lock.json
if not exist "package-lock.json" (
    echo 生成 package-lock.json...
    call npm install --package-lock-only
)

REM 下载所有依赖
echo 下载所有依赖包...
call npm cache clean --force
call npm install

REM 打包 node_modules (需要 7-Zip 或 tar)
echo 打包 node_modules...
if exist "%SCRIPT_DIR%node_modules.tar.gz" del "%SCRIPT_DIR%node_modules.tar.gz"

REM 尝试使用 tar (Windows 10+ 自带)
tar -czvf "%SCRIPT_DIR%node_modules.tar.gz" node_modules
if errorlevel 1 (
    echo 警告: tar 命令失败，尝试使用 7z...
    where 7z >nul 2>&1
    if errorlevel 1 (
        echo 错误: 需要 tar 或 7-Zip 来打包 node_modules
        echo 请手动压缩 node_modules 目录
        exit /b 1
    )
    7z a -ttar -so node_modules.tar node_modules | 7z a -si -tgzip "%SCRIPT_DIR%node_modules.tar.gz"
)

echo.
echo === 完成 ===
echo 离线包已保存到: %SCRIPT_DIR%node_modules.tar.gz
echo.
echo 在离线环境使用方法:
echo   1. 将 node_modules.tar.gz 复制到前端目录
echo   2. 运行: tar -xzvf node_modules.tar.gz
echo   3. 运行: npm run build

pause
