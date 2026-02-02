#!/usr/bin/env bash
# 将 Mac 上的 Coding 目录 rsync 同步到 UTM 虚拟机
# 使用前：在虚拟机内开启 SSH，并修改下方 UTM_VM_SSH、UTM_CODE_PATH

set -e

# ========== 配置：按你的环境修改 ==========
# 虚拟机 SSH，例如：kali@192.168.64.5 或 user@utm-kali.local
UTM_VM_SSH="${UTM_VM_SSH:-user@192.168.64.5}"

# 虚拟机上的代码目标目录（会与 Mac 源目录做 rsync 同步）
UTM_CODE_PATH="${UTM_CODE_PATH:-/home/user/coding}"

# Mac 上的代码源目录（当前项目根目录的上一级为 Coding）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# ========== 可选：排除的目录/文件 ==========
EXCLUDE=(
  --exclude '.git'
  --exclude '__pycache__'
  --exclude '.DS_Store'
  --exclude '*.pyc'
  --exclude '.idea'
  --exclude '*.qcow2'
  --exclude '*.fd'
  --exclude 'iso/*.iso'
)

# ========== 执行 rsync ==========
echo "Sync: $SOURCE_DIR/ -> $UTM_VM_SSH:$UTM_CODE_PATH/"
echo "Command: rsync -avz --delete ${EXCLUDE[*]} ..."
echo ""

rsync -avz --delete "${EXCLUDE[@]}" \
  "$SOURCE_DIR/" \
  "$UTM_VM_SSH:$UTM_CODE_PATH/"

echo "Done."
