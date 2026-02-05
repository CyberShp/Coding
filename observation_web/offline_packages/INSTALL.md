# 离线安装说明

本目录包含 observation_web 项目所需的所有依赖包，包括：
- **Python 后端依赖**：所有 wheel 包
- **Node.js 前端依赖**：预打包的 node_modules

## 支持的平台

- **macOS**: ARM64 (M1/M2)
- **Linux x86_64**: manylinux2014 兼容
- **Linux ARM64 (aarch64)**: manylinux2014 兼容（适用于 Euler ARM OS）
- **Windows**: win_amd64

## 支持的 Python 版本

- Python 3.7
- Python 3.8
- Python 3.9
- Python 3.10

> 注意：Python 3.6 由于部分依赖已不再支持，建议升级到 Python 3.7+

## 安装方法

### 方法一：使用 pip 批量安装（推荐）

```bash
# 进入离线包目录
cd observation_web/offline_packages

# 安装所有 wheel 包
pip install --no-index --find-links=. *.whl

# 如果有 tar.gz 源码包（如 SQLAlchemy），需要单独安装
pip install --no-index --find-links=. SQLAlchemy-1.4.50.tar.gz
```

### Windows 安装说明

Windows 仅需下载 win_amd64 相关的二进制 wheel 文件，纯 Python 包无需重复下载。

需要的 Windows wheel（示例）：

- `pydantic-*-win_amd64.whl` (cp37-cp310)
- `greenlet-*-win_amd64.whl` (cp37-cp310)
- `websockets-*-win_amd64.whl` (cp37-cp310)
- `cffi-*-win_amd64.whl` (cp37-cp310)
- `cryptography-*-win_amd64.whl`
- `bcrypt-*-win_amd64.whl`
- `pynacl-*-win_amd64.whl`

### 方法二：逐个安装

按以下顺序安装以满足依赖关系：

```bash
# 1. 基础依赖（无平台限制）
pip install typing_extensions-4.15.0-py3-none-any.whl
pip install pycparser-2.23-py3-none-any.whl
pip install dataclasses-0.6-py3-none-any.whl  # Python 3.6 only
pip install idna-3.11-py3-none-any.whl
pip install sniffio-1.3.1-py3-none-any.whl
pip install h11-0.16.0-py3-none-any.whl
pip install click-8.1.8-py3-none-any.whl

# 2. 平台相关包（根据平台选择对应版本）
# Linux x86_64 示例：
pip install cffi-2.0.0-cp39-cp39-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
pip install greenlet-3.0.0-cp39-cp39-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
pip install pydantic-1.10.12-cp39-cp39-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
pip install websockets-10.4-cp39-cp39-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl

# 3. 加密相关
pip install cryptography-43.0.3-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
pip install bcrypt-5.0.0-cp39-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
pip install pynacl-1.6.2-cp38-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl

# 4. 异步和网络
pip install anyio-4.12.1-py3-none-any.whl
pip install aiofiles-23.2.1-py3-none-any.whl
pip install aiosqlite-0.19.0-py3-none-any.whl

# 5. Web 框架
pip install starlette-0.27.0-py3-none-any.whl
pip install fastapi-0.95.2-py3-none-any.whl
pip install uvicorn-0.22.0-py3-none-any.whl
pip install python_multipart-0.0.6-py3-none-any.whl

# 6. SSH
pip install paramiko-3.3.1-py3-none-any.whl

# 7. 数据库
pip install SQLAlchemy-1.4.50.tar.gz
```

## 包文件说明

### 纯 Python 包（跨平台）
- `fastapi-0.95.2-py3-none-any.whl`
- `uvicorn-0.22.0-py3-none-any.whl`
- `starlette-0.27.0-py3-none-any.whl`
- `paramiko-3.3.1-py3-none-any.whl`
- `aiofiles-23.2.1-py3-none-any.whl`
- `aiosqlite-0.19.0-py3-none-any.whl`
- `anyio-4.12.1-py3-none-any.whl`
- `click-8.1.8-py3-none-any.whl`
- `h11-0.16.0-py3-none-any.whl`
- `idna-3.11-py3-none-any.whl`
- `sniffio-1.3.1-py3-none-any.whl`
- `typing_extensions-4.15.0-py3-none-any.whl`
- `pycparser-2.23-py3-none-any.whl`
- `python_multipart-0.0.6-py3-none-any.whl`
- `dataclasses-0.6-py3-none-any.whl` (仅 Python 3.6)
- `pydantic-1.10.12-py3-none-any.whl` (纯 Python 版本)

### 平台相关包

命名格式：`包名-版本-cpXX-cpXX-平台.whl`
- `cpXX`: Python 版本（如 cp39 = Python 3.9）
- `manylinux2014_x86_64`: Linux x86_64
- `manylinux2014_aarch64`: Linux ARM64
- `macosx_*`: macOS

### 源码包
- `SQLAlchemy-1.4.50.tar.gz` - 需要编译，目标系统需有 gcc

## 验证安装

```bash
python -c "import fastapi; import uvicorn; import paramiko; import sqlalchemy; print('All dependencies OK')"
```

## 常见问题

### Q: cffi 安装失败
A: cffi 需要 libffi 开发包，在 Linux 上：
```bash
# Euler/CentOS
yum install libffi-devel

# Ubuntu/Debian
apt install libffi-dev
```

### Q: cryptography 安装失败
A: 需要 OpenSSL 开发包：
```bash
# Euler/CentOS
yum install openssl-devel

# Ubuntu/Debian
apt install libssl-dev
```

### Q: SQLAlchemy 编译失败
A: 可以使用纯 Python 版本（性能略低）：
```bash
pip install SQLAlchemy --no-binary :all:
```

---

## 前端依赖（npm）离线安装

### 目录结构

```
offline_packages/npm/
├── node_modules.tar.gz     # 预打包的所有依赖（约35MB）
├── prepare-offline.sh      # Linux/macOS 准备脚本
├── prepare-offline.bat     # Windows 准备脚本
└── *.tgz                   # 主要依赖包（备用）
```

### 离线安装方法（推荐）

使用预打包的 `node_modules.tar.gz`：

```bash
# 1. 进入前端目录
cd observation_web/frontend

# 2. 解压 node_modules
tar -xzvf ../offline_packages/npm/node_modules.tar.gz

# 3. 构建前端
npm run build
```

**Windows 命令**：
```cmd
cd observation_web\frontend
tar -xzvf ..\offline_packages\npm\node_modules.tar.gz
npm run build
```

### 更新离线包

如果依赖有更新，在联网环境运行准备脚本重新生成离线包：

**Linux/macOS**：
```bash
cd observation_web/offline_packages/npm
chmod +x prepare-offline.sh
./prepare-offline.sh
```

**Windows**：
```cmd
cd observation_web\offline_packages\npm
prepare-offline.bat
```

### 备用方法：使用 tgz 包

如果预打包的 node_modules 不可用，可以使用单独的 tgz 包：

```bash
# 进入前端目录
cd observation_web/frontend

# 配置 npm 使用本地包
npm config set offline true

# 从本地安装（需要先将 tgz 放入 npm 缓存）
npm cache add ../offline_packages/npm/*.tgz
npm install --offline
```

### 包含的 npm 依赖

| 包名 | 版本 | 说明 |
|------|------|------|
| vue | 3.3.0 | Vue.js 框架 |
| vue-router | 4.2.0 | Vue 路由 |
| pinia | 2.1.0 | Vue 状态管理 |
| element-plus | 2.4.0 | UI 组件库 |
| axios | 1.6.0 | HTTP 客户端 |
| echarts | 5.4.0 | 图表库 |
| vue-echarts | 6.6.0 | ECharts Vue 封装 |
| @element-plus/icons-vue | 2.3.0 | Element Plus 图标 |
| vite | 5.0.0 | 构建工具 |
| @vitejs/plugin-vue | 4.5.0 | Vite Vue 插件 |
| sass | 1.69.0 | CSS 预处理器 |

### 前端常见问题

#### Q: node_modules.tar.gz 太大无法传输
A: 可以只传输构建好的 dist 目录，无需在目标环境重新构建：
```bash
# 联网环境构建
cd observation_web/frontend
npm install
npm run build

# 将 dist 目录复制到目标环境
```

#### Q: 解压 node_modules 后 npm run build 失败
A: 检查 Node.js 版本，建议使用 Node.js 18.x 或更高版本。

#### Q: Windows 上 tar 命令不可用
A: Windows 10 1803+ 自带 tar 命令。如果不可用，可以：
1. 使用 7-Zip 解压：右键 -> 7-Zip -> 解压到当前文件夹
2. 使用 Git Bash 自带的 tar
