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

## 前端依赖安装

前端需要 Node.js 18.x 或更高版本。

```bash
# 进入前端目录
cd observation_web/frontend

# 安装依赖（需要联网或配置 npm 镜像）
npm install

# 构建前端
npm run build
```

**离线环境**：建议在联网环境构建好 `dist` 目录后直接复制到目标环境使用。
