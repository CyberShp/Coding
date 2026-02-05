#!/bin/bash
# NPM 离线包准备脚本
# 在联网环境运行此脚本，下载所有 npm 依赖到当前目录

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/frontend"

echo "=== NPM 离线包准备脚本 ==="
echo "前端目录: $FRONTEND_DIR"
echo "输出目录: $SCRIPT_DIR"
echo ""

# 检查 npm
if ! command -v npm &> /dev/null; then
    echo "错误: npm 未安装"
    exit 1
fi

# 进入前端目录
cd "$FRONTEND_DIR"

# 确保有 package-lock.json
if [ ! -f "package-lock.json" ]; then
    echo "生成 package-lock.json..."
    npm install --package-lock-only
fi

# 使用 npm cache 方式下载所有依赖
echo "下载所有依赖包..."
npm cache clean --force
npm install --prefer-offline=false

# 打包 node_modules
echo "打包 node_modules..."
tar -czvf "$SCRIPT_DIR/node_modules.tar.gz" node_modules

echo ""
echo "=== 完成 ==="
echo "离线包已保存到: $SCRIPT_DIR/node_modules.tar.gz"
echo ""
echo "在离线环境使用方法:"
echo "  1. 将 node_modules.tar.gz 复制到前端目录"
echo "  2. 运行: tar -xzvf node_modules.tar.gz"
echo "  3. 运行: npm run build"
