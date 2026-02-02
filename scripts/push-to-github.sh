#!/usr/bin/env bash
# 一键添加、提交并提示推送到 GitHub（推送需你本机执行以完成认证）
set -e
cd "$(dirname "$0")/.."

echo "→ 添加变更..."
git add .gitignore observation_points/ scripts/ SYNC_UTM.md
git add -u observation_points/

if git diff --cached --quiet; then
  echo "无新变更，无需提交。"
  exit 0
fi

echo "→ 提交（如需可编辑提交信息）..."
MSG="${1:-chore: sync observation_points and scripts}"
git commit -m "$MSG"

echo ""
echo "=============================================="
echo "  请在本机执行以下命令完成推送到 GitHub："
echo "  cd $(pwd) && git push origin main"
echo "=============================================="
echo "（首次推送会要求登录 GitHub 或使用 SSH 密钥）"
