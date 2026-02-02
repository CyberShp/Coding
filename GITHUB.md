# 连接 GitHub

本仓库已配置远程：`origin` → `https://github.com/CyberShp/Coding.git`

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
