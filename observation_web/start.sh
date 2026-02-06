#!/bin/bash
# ============================================================
# Observation Web Advance - 一键启动脚本
# 同时启动后端 (FastAPI) 和前端 (Vite Dev Server)
# 使用方式: ./start.sh [--prod]
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  Observation Web Advance 启动中...  ${NC}"
echo -e "${GREEN}=====================================${NC}"

# Check Python
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}错误: 未找到 Python，请先安装 Python 3.8+${NC}"
    exit 1
fi

echo -e "${GREEN}Python: $($PYTHON_CMD --version)${NC}"

# Check Node.js
if ! command -v npm &>/dev/null; then
    echo -e "${RED}错误: 未找到 npm，请先安装 Node.js${NC}"
    exit 1
fi
echo -e "${GREEN}Node.js: $(node --version)${NC}"

# Install backend dependencies if needed
if ! $PYTHON_CMD -c "import fastapi" 2>/dev/null; then
    echo -e "${YELLOW}安装后端依赖...${NC}"
    $PYTHON_CMD -m pip install -r requirements.txt -q
fi

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo -e "${YELLOW}安装前端依赖...${NC}"
    cd frontend && npm install && cd ..
fi

# Determine mode
PROD_MODE=false
if [ "$1" = "--prod" ]; then
    PROD_MODE=true
fi

# Start backend
echo -e "${GREEN}启动后端服务 (FastAPI)...${NC}"
$PYTHON_CMD -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo -e "  后端 PID: $BACKEND_PID"

# Start frontend
echo -e "${GREEN}启动前端服务 (Vite)...${NC}"
cd frontend
if [ "$PROD_MODE" = true ]; then
    npm run build
    echo -e "${YELLOW}前端已构建，请使用 nginx 或其他 Web 服务器托管 dist/ 目录${NC}"
else
    npm run dev &
    FRONTEND_PID=$!
    echo -e "  前端 PID: $FRONTEND_PID"
fi
cd ..

echo ""
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  服务已启动!                        ${NC}"
echo -e "${GREEN}  后端 API: http://localhost:8000     ${NC}"
echo -e "${GREEN}  前端界面: http://localhost:5173     ${NC}"
echo -e "${GREEN}  API 文档: http://localhost:8000/docs${NC}"
echo -e "${GREEN}=====================================${NC}"
echo ""
echo -e "${YELLOW}按 Ctrl+C 停止所有服务${NC}"

# Handle Ctrl+C gracefully
cleanup() {
    echo ""
    echo -e "${YELLOW}正在停止服务...${NC}"
    
    if [ -n "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo "  后端服务已停止"
    fi
    
    if [ -n "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
        echo "  前端服务已停止"
    fi
    
    echo -e "${GREEN}所有服务已停止${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for any background process to finish
wait
