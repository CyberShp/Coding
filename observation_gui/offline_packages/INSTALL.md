# Paramiko 离线安装包

本目录包含 paramiko 及其依赖的离线安装包，支持以下平台：

| 平台 | 架构 | Python 版本 |
|------|------|-------------|
| Windows | x86_64 | 3.9+ |
| Linux | x86_64 | 3.9+ |
| Linux | ARM64 (aarch64) | 3.9+ |
| macOS | Universal (x86_64/ARM64) | 3.9+ |

## 离线安装方法

### Windows (x64)

```powershell
cd offline_packages
pip install --no-index --find-links=. paramiko
```

### Linux x86_64

```bash
cd offline_packages
pip3 install --no-index --find-links=. paramiko
```

### Linux ARM64 (aarch64)

```bash
cd offline_packages
pip3 install --no-index --find-links=. paramiko
```

### macOS

```bash
cd offline_packages
pip3 install --no-index --find-links=. paramiko
```

## 包含的包

- `paramiko-4.0.0` - SSH 库（纯 Python，跨平台）
- `cryptography-43.0.3/46.0.4` - 加密库（平台相关）
- `bcrypt-5.0.0` - 密码哈希（平台相关）
- `pynacl-1.6.2` - NaCl 加密绑定（平台相关）
- `cffi-2.0.0` - C 外部函数接口（平台相关）
- `pycparser-2.23` - C 解析器（纯 Python）
- `invoke-2.2.1` - 任务执行库（纯 Python）
- `typing_extensions-4.15.0` - 类型提示扩展（纯 Python）

## 注意事项

1. 确保 Python 版本 >= 3.9
2. 如果安装失败，检查是否选择了正确的平台包
3. 对于其他 Python 版本，可能需要重新下载对应版本的 wheel 文件
