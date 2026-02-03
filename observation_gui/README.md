# 观察点可视化监控平台

基于 Tkinter 的多阵列可视化监控工具，通过 SSH 连接远程阵列执行监控任务。

## 功能特性

- **多阵列管理**：同时监控多台存储阵列
- **SSH 连接**：支持密码和密钥认证
- **实时状态**：显示各观察点的监控状态
- **告警展示**：实时显示最近的告警信息
- **自动刷新**：定时刷新监控数据

## 系统要求

- Python 3.8+（Tkinter 内置）
- paramiko >= 2.7.0（SSH 连接）

## 安装

```bash
# 安装依赖
pip install -r requirements.txt
```

## 运行

```bash
# 从项目根目录运行
cd /Volumes/Media/Coding
python3 -m observation_gui
```

## 使用说明

### 添加阵列

1. 点击 "阵列" 菜单 -> "添加阵列"
2. 输入阵列名称、主机地址、端口、用户名
3. 选择认证方式（密码或密钥文件）
4. 点击确定

### 连接阵列

- 选中阵列后，双击或点击 "连接" 按钮
- 连接成功后，图标变为实心圆点

### 启动监控

1. 确保阵列上已部署 `observation_points`
2. 选中已连接的阵列
3. 点击 "阵列" 菜单 -> "启动监控"

### 查看状态

- 左侧面板显示阵列列表和连接状态
- 右侧面板显示选中阵列的详细状态
- 状态栏显示全局统计信息

## 项目结构

```
observation_gui/
├── __init__.py         # 包初始化
├── __main__.py         # 主入口
├── requirements.txt    # 依赖
├── config.json         # 配置文件
├── README.md           # 说明文档
│
├── gui/                # Tkinter 界面
│   ├── main_window.py  # 主窗口
│   ├── login_dialog.py # 登录对话框
│   ├── array_panel.py  # 阵列详情面板
│   └── status_bar.py   # 状态栏
│
├── ssh/                # SSH 连接
│   ├── connector.py    # SSH 连接器
│   └── remote_ops.py   # 远程操作
│
└── core/               # 核心逻辑
    ├── array_manager.py    # 阵列管理器
    └── result_parser.py    # 结果解析
```

## 配置文件

`config.json` 包含以下配置项：

```json
{
  "app": {
    "title": "观察点监控平台",
    "refresh_interval": 30,
    "window_width": 1000,
    "window_height": 700
  },
  "ssh": {
    "default_port": 22,
    "timeout": 10
  },
  "remote": {
    "agent_path": "/opt/observation_points",
    "log_path": "/var/log/observation-points/alerts.log"
  },
  "arrays": []
}
```

## 与 observation_points 配合使用

1. 将 `observation_points` 部署到目标阵列的 `/opt/observation_points`
2. 使用本工具连接到阵列
3. 通过 GUI 启动/停止监控
4. 实时查看监控状态和告警

## 许可证

内部使用
