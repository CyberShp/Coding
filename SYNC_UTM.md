# Mac Mini Cursor 代码目录 → UTM 虚拟机同步指南

将 `/Volumes/Media/Coding`（或你指定的 code 目录）同步到 UTM 虚拟机，有两种常用方式：**UTM 共享目录（推荐）** 和 **rsync over SSH**。

---

## 方案一：UTM 共享目录（VirtFS，推荐）

虚拟机直接挂载 Mac 上的目录，无需复制，修改实时可见。你的 Kali Linux 2023 已使用 QEMU 后端且支持 VirtFS。

### 1. 在 Mac 上（UTM 里）配置共享目录

1. **关闭虚拟机**（VirtFS 共享目录不能在运行中修改）。
2. 打开 **UTM** → 选中你的 VM（如 Kali Linux 2023）→ 点击 **编辑**。
3. 进入 **Sharing / 共享** 设置：
   - **Directory Sharing** 选择 **VirtFS**（你已是此模式）。
   - 点击 **Browse / 浏览**，选择要共享的目录：
     - 推荐：`/Volumes/Media/Coding`（整个代码盘）
     - 或只共享某个子目录，例如：`/Volumes/Media/Coding/observation_points`
4. 如需只读可勾选 **Read Only**，否则保持可读写。
5. 保存配置，**启动虚拟机**。

### 2. 在 Linux 虚拟机内挂载共享目录

#### 临时挂载（重启后失效）

```bash
# 创建挂载点
sudo mkdir -p /mnt/coding

# 挂载 UTM 的 VirtFS 共享（tag 固定为 share）
sudo mount -t 9p -o trans=virtio,version=9p2000.L share /mnt/coding
```

之后代码在 `/mnt/coding` 下可见。

#### 开机自动挂载（推荐）

```bash
# 创建挂载点
sudo mkdir -p /mnt/coding

# 编辑 fstab
sudo nano /etc/fstab
```

在文件末尾添加一行（UTM 的 VirtFS 设备名固定为 `share`）：

```
# UTM 共享：Mac Coding 目录
share /mnt/coding 9p trans=virtio,version=9p2000.L,rw,_netdev,nofail,auto 0 0
```

保存后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart remote-fs.target   # 或 network-fs.target
# 若无上述 unit，可直接： sudo mount -a
```

### 3. 权限问题（可选）

若在挂载点内访问文件出现 “Permission denied”，可用以下两种方式之一：

**方式 A：用 bindfs 映射 UID/GID（适合长期使用）**

```bash
# 安装 bindfs（Debian/Ubuntu/Kali）
sudo apt install bindfs

# 查看主机 UID/GID（在 /mnt/coding 下 ls -na 看到的数字）
ls -na /mnt/coding

# 假设主机是 502:20，虚拟机当前用户是 1000:1000
mkdir -p ~/coding
# 在 /etc/fstab 再加一行（把 502、20、1000 换成你 ls -na 看到的）
# /mnt/coding /home/你的用户名/coding fuse.bindfs map=502/1000:@20/@1000,x-systemd.requires=/mnt/coding,_netdev,nofail,auto 0 0
```

**方式 B：简单改挂载点内所有权（会写扩展属性，不适合共享整个 home）**

```bash
sudo chown -R $USER /mnt/coding
```

---

## 方案二：rsync 同步（适合无 VirtFS 或需“快照式”同步）

当 VM 未开共享目录、或你希望把代码“推一份”到虚拟机指定目录时，可用 rsync over SSH。

### 前提

- 虚拟机已安装并开启 **SSH 服务**。
- Mac 能通过 IP 或主机名 SSH 到虚拟机（例如 `ssh user@192.168.64.x`）。

### 使用项目自带脚本（推荐）

项目根目录下提供了 `scripts/sync-to-utm.sh`，用法：

```bash
# 编辑脚本，设置 VM 的 SSH 地址与目标路径
# UTM_VM_SSH="user@192.168.64.x"
# UTM_CODE_PATH="/home/user/coding"

./scripts/sync-to-utm.sh
```

脚本会使用 rsync 将 `/Volumes/Media/Coding` 同步到虚拟机上的 `UTM_CODE_PATH`（排除常见无关目录）。

### 手动 rsync 示例

```bash
# 将 Mac 的 Coding 目录同步到 VM 的 /home/user/coding
rsync -avz --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  --exclude '*.pyc' \
  /Volumes/Media/Coding/ user@虚拟机IP:/home/user/coding/
```

按需修改 `user`、`虚拟机IP` 和 `/home/user/coding/`。

---

## 目录对照

| 位置           | 路径说明 |
|----------------|----------|
| Mac（主机）    | `/Volumes/Media/Coding` — 你当前的 code 目录 |
| UTM 共享挂载点 | 虚拟机内例如 `/mnt/coding` 或 `~/coding`（bindfs 时） |
| rsync 目标     | 虚拟机内你指定的目录，如 `/home/user/coding` |

---

## 常见问题

- **共享目录在 UTM 里选不了 / 重启后没了**  
  共享路径需在 **VM 未运行** 时设置；若仍不持久，可查看 [UTM 官方文档](https://docs.getutm.app/settings-qemu/sharing/) 或考虑用 rsync 方案兜底。

- **Linux 里没有 9p 或 mount 报错**  
  确认内核支持 9p：`sudo modinfo 9pnet_virtio`；Kali 一般已包含。

- **只同步部分项目**  
  在 UTM 共享时只选择子目录（如 `observation_points`），或修改 rsync 的源路径与 exclude 规则。

按上述任选一种方式配置后，即可在 UTM 虚拟机中稳定使用 Mac 上的代码目录。
