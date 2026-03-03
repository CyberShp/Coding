#!/bin/bash
# ============================================================
# Observation Web - 服务器升级脚本
# 使用方式: ./scripts/upgrade.sh <升级包.tar.gz>
#          ./scripts/upgrade.sh --rollback  # 回滚到最近备份
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$INSTALL_DIR/backups"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

rollback() {
    LATEST=$(ls -td "$BACKUP_DIR"/backup_* 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then
        echo -e "${RED}无可用备份${NC}"
        exit 1
    fi
    echo -e "${YELLOW}回滚到: $LATEST${NC}"
    pkill -f "uvicorn.*backend.main" 2>/dev/null || true
    sleep 2
    cp -a "$LATEST"/* "$INSTALL_DIR/"
    cp -a "$LATEST"/. "$INSTALL_DIR/" 2>/dev/null || true
    echo -e "${GREEN}回滚完成，请手动启动服务${NC}"
    exit 0
}

[ "$1" = "--rollback" ] && rollback

PACK_FILE="$1"
if [ -z "$PACK_FILE" ] || [ ! -f "$PACK_FILE" ]; then
    echo -e "${RED}用法: $0 <升级包.tar.gz>${NC}"
    echo -e "  或: $0 --rollback"
    exit 1
fi

# Resolve absolute path
PACK_FILE="$(cd "$(dirname "$PACK_FILE")" && pwd)/$(basename "$PACK_FILE")"

echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  Observation Web 升级                ${NC}"
echo -e "${GREEN}=====================================${NC}"

# 1. Backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
BACKUP_PATH="$BACKUP_DIR/backup_$TIMESTAMP"
echo -e "${YELLOW}备份到 $BACKUP_PATH${NC}"
mkdir -p "$BACKUP_PATH"
cp -a "$INSTALL_DIR"/backend "$BACKUP_PATH/" 2>/dev/null || true
cp -a "$INSTALL_DIR"/agent "$BACKUP_PATH/" 2>/dev/null || true
cp -a "$INSTALL_DIR"/frontend "$BACKUP_PATH/" 2>/dev/null || true
cp -a "$INSTALL_DIR"/scripts "$BACKUP_PATH/" 2>/dev/null || true
[ -f "$INSTALL_DIR/config.json" ] && cp "$INSTALL_DIR/config.json" "$BACKUP_PATH/"
[ -f "$INSTALL_DIR/observation_web.db" ] && cp "$INSTALL_DIR/observation_web.db" "$BACKUP_PATH/"
[ -f "$INSTALL_DIR/requirements.txt" ] && cp "$INSTALL_DIR/requirements.txt" "$BACKUP_PATH/"
[ -f "$INSTALL_DIR/start.sh" ] && cp "$INSTALL_DIR/start.sh" "$BACKUP_PATH/"

# 2. Stop service
echo -e "${YELLOW}停止服务...${NC}"
pkill -f "uvicorn.*backend.main" 2>/dev/null || true
sleep 2

# 3. Extract and replace
TMP_EXTRACT=$(mktemp -d)
tar xzf "$PACK_FILE" -C "$TMP_EXTRACT"
SRC=$(ls -d "$TMP_EXTRACT"/observation_web_v* 2>/dev/null | head -1)
if [ -z "$SRC" ]; then
    SRC="$TMP_EXTRACT/$(ls "$TMP_EXTRACT" | head -1)"
fi

echo -e "${YELLOW}替换代码...${NC}"
cp -r "$SRC"/backend "$INSTALL_DIR/"
cp -r "$SRC"/agent "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/frontend"
cp -r "$SRC"/frontend/dist "$INSTALL_DIR/frontend/"
cp -r "$SRC"/scripts "$INSTALL_DIR/"
cp "$SRC"/requirements.txt "$INSTALL_DIR/"
cp "$SRC"/start.sh "$INSTALL_DIR/"
[ -f "$SRC/config.json.example" ] && cp "$SRC/config.json.example" "$INSTALL_DIR/" || true

# Preserve config and db
[ -f "$BACKUP_PATH/config.json" ] && cp "$BACKUP_PATH/config.json" "$INSTALL_DIR/"
[ -f "$BACKUP_PATH/observation_web.db" ] && cp "$BACKUP_PATH/observation_web.db" "$INSTALL_DIR/"

rm -rf "$TMP_EXTRACT"

# 4. Install deps
echo -e "${YELLOW}安装依赖...${NC}"
cd "$INSTALL_DIR"
if [ -d "vendor" ]; then
    python3 -m pip install --no-index --find-links=vendor -r requirements.txt -q
else
    python3 -m pip install -r requirements.txt -q
fi

# 5. Run migrations
echo -e "${YELLOW}执行数据库迁移...${NC}"
python3 -c "
import asyncio
import sys
sys.path.insert(0, '.')
from backend.db.database import init_db, create_tables
init_db()
asyncio.run(create_tables())
print('Migrations OK')
"

# 6. Start service
echo -e "${YELLOW}启动服务...${NC}"
PORT=$(python3 -c "
import json
with open('config.json') as f:
    c = json.load(f)
print(c.get('server', {}).get('port', 9999))
" 2>/dev/null || echo "9999")

python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" &
sleep 3

# 7. Health check
if curl -sf "http://localhost:$PORT/health" >/dev/null; then
    echo ""
    echo -e "${GREEN}=====================================${NC}"
    echo -e "${GREEN}  升级完成!                          ${NC}"
    echo -e "${GREEN}=====================================${NC}"
    echo -e "  服务: http://localhost:$PORT"
    echo -e "  备份: $BACKUP_PATH"
else
    echo -e "${RED}健康检查失败，请检查日志${NC}"
    echo -e "${YELLOW}回滚: ./scripts/upgrade.sh --rollback${NC}"
    exit 1
fi
