# 离线安装指南

本目录包含所有 Python 后端依赖的离线安装包。

## 目录结构

```
offline_packages/
├── pip/                    # Python wheel 包 (Linux x86_64 + Windows x64)
│   ├── fastapi-*.whl
│   ├── uvicorn-*.whl
│   ├── paramiko-*.whl
│   ├── sqlalchemy-*.whl
│   ├── apscheduler-*.whl
│   └── ...
└── INSTALL.md             # 本文件
```

## 支持的平台

- **Linux**: manylinux2014_x86_64 (CentOS 7+, Ubuntu 18.04+, etc.)
- **Windows**: win_amd64 (Windows 64-bit)
- **Python**: 3.8+

## 离线安装步骤

### 1. 复制离线包

将 `offline_packages/pip/` 目录复制到目标服务器。

### 2. 安装 Python 依赖

```bash
# Linux/macOS
pip install --no-index --find-links=/path/to/offline_packages/pip -r requirements.txt

# Windows
pip install --no-index --find-links=C:\path\to\offline_packages\pip -r requirements.txt
```

### 3. 验证安装

```bash
python -c "import fastapi, uvicorn, paramiko, sqlalchemy, apscheduler; print('All packages installed successfully!')"
```

## 包含的依赖包

| 包名 | 用途 |
|------|------|
| fastapi | Web 框架 |
| uvicorn | ASGI 服务器 |
| paramiko | SSH 连接 |
| sqlalchemy | 数据库 ORM |
| aiosqlite | 异步 SQLite |
| pydantic | 数据验证 |
| aiofiles | 异步文件操作 |
| websockets | WebSocket 支持 |
| apscheduler | 定时任务调度 |
| python-multipart | 文件上传 |
| cryptography | 加密支持 |
| bcrypt | 密码哈希 |
| pynacl | 安全加密 |

## 前端依赖

前端使用 Node.js + npm，需要在有网络的环境下执行：

```bash
cd frontend
npm install
npm run build
```

构建产物在 `frontend/dist/` 目录。

## 注意事项

1. 确保目标服务器的 Python 版本 >= 3.8
2. Linux 服务器需要 glibc 2.17+ (CentOS 7+)
3. 某些包（如 uvloop）仅支持 Linux，Windows 用户无需安装
