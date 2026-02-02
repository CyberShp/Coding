#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 Chrome 浏览器图形界面，将 observation_points 项目连接到 GitHub 仓库。

用法:
  pip install -r scripts/requirements-connect.txt
  playwright install chromium   # 或使用系统 Chrome（脚本默认尝试 channel=chrome）
  python scripts/connect_observation_points_to_github.py

脚本会：
  1. 打开 Chrome，进入 GitHub 新建仓库页面（仓库名预填 observation_points）
  2. 你可手动点击「Create repository」完成创建（或由脚本尝试点击）
  3. 创建后，按终端提示执行 git 命令完成连接与推送
"""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("请先安装 Playwright：")
    print("  pip install playwright")
    print("  playwright install chromium")
    sys.exit(1)

# 仓库根目录（Coding 目录）
REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_NEW_REPO = "https://github.com/new"
DEFAULT_REPO_NAME = "observation_points"
DEFAULT_DESCRIPTION = "Observation points monitoring project - 观察点监控系统"


def get_current_remote():
    """获取当前 git remote origin URL。"""
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def run_browser_flow(
    repo_name: str = DEFAULT_REPO_NAME,
    description: str = DEFAULT_DESCRIPTION,
    use_chrome: bool = True,
    headless: bool = False,
    auto_click_create: bool = False,
):
    params = "&".join(
        [
            f"name={repo_name}",
            f"description={description.replace(' ', '+')}",
        ]
    )
    url = f"{GITHUB_NEW_REPO}?{params}"

    launch_options = {"headless": headless}
    if use_chrome:
        # 使用系统已安装的 Chrome（若已安装 Playwright 的 Chrome 驱动）
        launch_options["channel"] = "chrome"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**launch_options)
        except Exception:
            browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(1500)

        if auto_click_create:
            try:
                # 尝试点击 "Create repository"
                create_btn = page.get_by_role("button", name="Create repository")
                create_btn.click()
                page.wait_for_timeout(3000)
            except Exception as e:
                print("自动点击未成功，请手动在浏览器中点击「Create repository」。", e)

        print("\n请在 Chrome 中完成：")
        print("  1. 确认仓库名为:", repo_name)
        print("  2. 选择 Public/Private")
        print("  3. 不要勾选「Add a README」（本地已有）")
        print("  4. 点击「Create repository」")
        input("\n完成后按 Enter 继续...")

        # 当前页应是新仓库页，可解析出 owner/repo
        current_url = page.url
        browser.close()

    # 从 URL 解析 owner/repo，例如 https://github.com/sr1shepard/observation_points
    if "github.com" in current_url and current_url.rstrip("/").count("/") >= 4:
        parts = current_url.rstrip("/").split("/")
        owner = parts[-2]
        repo = parts[-1]
        if repo == "new":
            owner, repo = "", ""
    else:
        owner = repo = ""
    return owner, repo


def main():
    parser = argparse.ArgumentParser(
        description="通过 Chrome 将 observation_points 连接到 GitHub 仓库"
    )
    parser.add_argument(
        "--repo-name",
        default=DEFAULT_REPO_NAME,
        help="GitHub 仓库名（默认: observation_points）",
    )
    parser.add_argument(
        "--description",
        default=DEFAULT_DESCRIPTION,
        help="仓库简短描述",
    )
    parser.add_argument(
        "--no-chrome",
        action="store_true",
        help="使用 Playwright 自带的 Chromium 而非系统 Chrome",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（不打开浏览器窗口，仅用于已有仓库时打印命令）",
    )
    parser.add_argument(
        "--auto-click",
        action="store_true",
        help="尝试自动点击「Create repository」（可能需人工完成验证）",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="跳过浏览器，仅根据 --repo-name 和当前用户打印 git 命令（需已知 owner）",
    )
    parser.add_argument(
        "--owner",
        default="",
        help="GitHub 用户名或组织（与 --skip-browser 一起用）",
    )
    args = parser.parse_args()

    if args.skip_browser:
        owner = args.owner or "sr1shepard"
        repo = args.repo_name
        print(f"\n假设仓库为: https://github.com/{owner}/{repo}")
        print_git_commands(owner, repo)
        return

    print("正在启动 Chrome 并打开 GitHub 新建仓库页面...")
    owner, repo = run_browser_flow(
        repo_name=args.repo_name,
        description=args.description,
        use_chrome=not args.no_chrome,
        headless=args.headless,
        auto_click_create=args.auto_click,
    )
    if not owner or not repo:
        print("未能从浏览器 URL 解析出 owner/repo，请手动执行下方命令并替换 YOUR_USERNAME。")
        owner = "YOUR_USERNAME"
        repo = args.repo_name
    print_git_commands(owner, repo)


def print_git_commands(owner: str, repo: str):
    remote_url = f"https://github.com/{owner}/{repo}.git"
    ssh_url = f"git@github.com:{owner}/{repo}.git"
    print("\n" + "=" * 60)
    print("  连接并推送到 GitHub：在项目根目录执行以下命令")
    print("=" * 60)
    print(f"\n  cd {REPO_ROOT}")
    print("\n  # 若当前 origin 不是目标仓库，可更换远程：")
    print(f"  git remote set-url origin {remote_url}")
    print("  # 或使用 SSH：")
    print(f"  # git remote set-url origin {ssh_url}")
    print("\n  # 推送（首次会提示登录或使用 Personal Access Token）：")
    print("  git push -u origin main")
    print("\n  若尚未提交 observation_points 的变更，可先执行：")
    print("  ./scripts/push-to-github.sh \"你的提交说明\"")
    print("  再执行上面的 git push。")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
