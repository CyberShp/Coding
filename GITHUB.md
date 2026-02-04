# 连接 GitHub

本仓库已配置远程：`origin` → `https://github.com/CyberShp/Coding.git`

（若该地址 404 或你想把 observation_points 单独建仓，可用下方「通过 Chrome 图形界面连接」。）

---

## 报错：Invalid username or token / Password authentication is not supported

说明 GitHub **不再接受账号密码**，必须用下面两种方式之一。

### 方式一：用 Personal Access Token（HTTPS，推荐先试）

1. 打开：<https://github.com/settings/tokens> → **Generate new token (classic)**。
2. Note 填 `Coding`，Expiration 选 90 days 或 No expiration，勾选 **repo**。
3. 生成后**复制 token**（只显示一次，务必保存）。
4. 在终端执行：
   ```bash
   cd /Volumes/Media/Coding
   git push origin main
   ```
5. 用户名填你的 **GitHub 用户名**，密码处**粘贴刚才的 token**（不要填登录密码）。

### 方式二：用 SSH 密钥（一次配置长期使用）

若本机已有 SSH 公钥（如 `~/.ssh/id_ed25519.pub` 或 `id_rsa.pub`）：

1. 把公钥内容添加到 GitHub：<https://github.com/settings/keys> → **New SSH key**。
2. 把远程改为 SSH 并推送：
   ```bash
   cd /Volumes/Media/Coding
   git remote set-url origin git@github.com:CyberShp/Coding.git
   git push origin main
   ```

若还没有 SSH 密钥，可先生成再按上面添加：

```bash
ssh-keygen -t ed25519 -C "你的邮箱" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub   # 复制输出，粘贴到 GitHub SSH keys 页
```

### SSH 报错：Connection closed by ... port 22

说明当前网络封锁了 22 端口。让 GitHub 走 **443 端口**：在 `~/.ssh/config` 里加入：

```
Host github.com
  Hostname ssh.github.com
  Port 443
  User git
  StrictHostKeyChecking accept-new
```

保存后重试：`ssh -T git@github.com`，再 `git push origin main`。

---

## 通过 Chrome 图形界面连接（推荐）

用浏览器自动化在 GitHub 上新建仓库并拿到推送命令：

```bash
pip install playwright
playwright install chromium
python scripts/connect_observation_points_to_github.py
```

脚本会打开 Chrome，进入 GitHub 新建仓库页（仓库名预填 `observation_points`）。在页面中点击「Create repository」后，回到终端按 Enter，脚本会输出 `git remote` 和 `git push` 命令，按提示执行即可完成连接与推送。

可选参数：`--no-chrome` 使用自带 Chromium；`--auto-click` 尝试自动点击创建按钮；`--skip-browser --owner 你的用户名` 只打印命令不打开浏览器。

## 你需要参与的一步：首次推送 / 认证

在终端执行（只需做一次，或在你本机首次推送到该仓库时）：

```bash
cd /Volumes/Media/Coding
git push origin main
```

- **HTTPS**：会提示输入 GitHub 用户名和密码；密码请使用 [Personal Access Token](https://github.com/settings/tokens)（不再支持账号密码）。
- **SSH**：若已配置 SSH 密钥，可把远程改为 SSH 后推送：
  ```bash
  git remote set-url origin git@github.com:CyberShp/Coding.git
  git push origin main
  ```

## 日常同步（自动化）

以后提交并推送可用：

```bash
./scripts/push-to-github.sh "你的提交说明"
# 然后执行脚本最后提示的：git push origin main
```

或手动：

```bash
git add .
git commit -m "说明"
git push origin main
```

## 当前状态

- 已提交：`.gitignore`、`observation_points/` 更新、`scripts/`、`SYNC_UTM.md`
- 已忽略大文件：`.DS_Store`、`.idea/`、`*.iso`、`*.qcow2` 等（见 `.gitignore`）
