#!/bin/bash
# ============================================================
# Observation Web - 本地打包脚本
# 产出升级包 observation_web_vX.Y.Z_YYYYMMDD.tar.gz
# 使用方式: ./scripts/pack.sh [--with-deps]
#   --with-deps: 打入 Python wheel 离线依赖到 vendor/
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get version
VERSION=$(python3 -c "from backend.config import __version__; print(__version__)" 2>/dev/null || echo "4.0.0")
TIMESTAMP=$(date +%Y%m%d)
PACK_NAME="observation_web_v${VERSION}_${TIMESTAMP}"
TMP_DIR=$(mktemp -d)
PACK_DIR="$TMP_DIR/$PACK_NAME"
WITH_DEPS=false

for arg in "$@"; do
    [ "$arg" = "--with-deps" ] && WITH_DEPS=true
done

echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  Observation Web 打包 v${VERSION}     ${NC}"
echo -e "${GREEN}=====================================${NC}"

# Build frontend
echo -e "${YELLOW}构建前端...${NC}"
cd frontend
npm run build
cd ..
echo -e "${GREEN}前端构建完成${NC}"

# Create package structure
mkdir -p "$PACK_DIR"
cp -r backend "$PACK_DIR/"
cp -r agent "$PACK_DIR/"
cp -r frontend/dist "$PACK_DIR/frontend/"
cp requirements.txt "$PACK_DIR/"
cp start.sh "$PACK_DIR/"
[ -f config.json.example ] && cp config.json.example "$PACK_DIR/" || true

# Copy scripts (including upgrade.sh for server)
mkdir -p "$PACK_DIR/scripts"
cp scripts/pack.sh "$PACK_DIR/scripts/" 2>/dev/null || true
[ -f scripts/upgrade.sh ] && cp scripts/upgrade.sh "$PACK_DIR/scripts/" || true

# Write VERSION file
echo "$VERSION" > "$PACK_DIR/VERSION"

# Clean excludes
find "$PACK_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$PACK_DIR" -type d -name "*.pyc" -exec rm -rf {} + 2>/dev/null || true
find "$PACK_DIR" -type f -name "*.db" -delete 2>/dev/null || true
find "$PACK_DIR" -type f -name "*.log" -delete 2>/dev/null || true

# Offline deps
if [ "$WITH_DEPS" = true ]; then
    echo -e "${YELLOW}下载 Python 离线依赖...${NC}"
    mkdir -p "$PACK_DIR/vendor"
    python3 -m pip download -r requirements.txt -d "$PACK_DIR/vendor" -q
    echo -e "${GREEN}离线依赖已打入 vendor/${NC}"
fi

# Create tarball
cd "$TMP_DIR"
tar czf "${PACK_NAME}.tar.gz" "$PACK_NAME"
mv "${PACK_NAME}.tar.gz" "$PROJECT_DIR/"
cd "$PROJECT_DIR"
rm -rf "$TMP_DIR"

OUTPUT="$PROJECT_DIR/${PACK_NAME}.tar.gz"
SIZE=$(du -h "$OUTPUT" | cut -f1)
COUNT=$(tar tzf "$OUTPUT" | wc -l)

echo ""
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  打包完成!                          ${NC}"
echo -e "${GREEN}=====================================${NC}"
echo -e "  输出: ${OUTPUT}"
echo -e "  大小: ${SIZE}"
echo -e "  文件数: ${COUNT}"
echo ""
echo -e "${YELLOW}升级步骤:${NC}"
echo -e "  1. scp ${PACK_NAME}.tar.gz user@server:/path/to/observation_web/"
echo -e "  2. ssh user@server"
echo -e "  3. cd /path/to/observation_web && ./scripts/upgrade.sh ${PACK_NAME}.tar.gz"
echo ""
