# 观察点监控平台 - Web 版

基于 FastAPI + Vue 3 的存储阵列监控平台 Web 服务，用于集中管理和监控多台存储阵列的健康状态。

## 功能特性

### 核心功能
- **多阵列管理**: 集中管理多台存储阵列，支持 SSH 密码和密钥认证
- **实时监控**: WebSocket 实时推送告警，无需手动刷新
- **Agent 部署**: 一键部署和管理远程观察点 Agent
- **告警同步**: 自动同步远程阵列的告警到本地数据库
- **自定义查询**: 灵活的 SSH 命令执行和正则匹配

### 监控能力
- 误码监测 (error_code)
- 链路状态 (link_status)
- 卡修复监测 (card_recovery)
- AlarmType 告警 (alarm_type)
- 内存泄漏检测 (memory_leak)
- CPU 利用率 (cpu_usage)
- 命令响应 (cmd_response)
- 信号监测 (sig_monitor)
- 敏感信息检测 (sensitive_info)

### 系统功能
- **系统告警**: 后端错误追踪和调试信息展示
- **自动重连**: SSH 连接断开后自动尝试重连（最多3次）
- **告警统计**: 24小时告警趋势图、按级别/观察点统计

## 技术栈

### 后端
- **FastAPI**: 高性能异步 Web 框架
- **SQLite + SQLAlchemy**: 轻量级数据库
- **Paramiko**: SSH 连接管理
- **WebSocket**: 实时通信

### 前端
- **Vue 3 + Vite**: 现代化前端构建
- **Element Plus**: UI 组件库
- **ECharts**: 图表可视化
- **Pinia**: 状态管理
- **Axios**: HTTP 请求

## 目录结构

```
observation_web/
├── backend/                # FastAPI 后端
│   ├── main.py            # 应用入口、中间件
│   ├── config.py          # 配置管理
│   ├── api/               # API 路由
│   │   ├── arrays.py      # 阵列管理 API
│   │   ├── alerts.py      # 告警查询 API
│   │   ├── query.py       # 自定义查询 API
│   │   ├── websocket.py   # WebSocket 端点
│   │   └── system_alerts.py # 系统告警 API
│   ├── core/              # 核心逻辑
│   │   ├── ssh_pool.py    # SSH 连接池
│   │   ├── agent_deployer.py # Agent 部署
│   │   ├── alert_store.py # 告警存储
│   │   └── system_alert.py # 系统告警
│   ├── models/            # 数据模型
│   └── db/                # 数据库
├── frontend/              # Vue 3 前端
│   ├── src/
│   │   ├── views/        # 页面组件
│   │   ├── api/          # API 封装
│   │   ├── stores/       # 状态管理
│   │   └── router/       # 路由配置
│   ├── package.json
│   └── vite.config.js
├── offline_packages/      # 离线安装包
├── config.json            # 配置文件
└── requirements.txt       # Python 依赖
```

## 快速开始

### 环境要求
- Python 3.7+ (推荐 3.9+)
- Node.js 18+ (前端开发)
- SSH 访问目标阵列的权限

### 1. 安装后端依赖

```bash
cd observation_web
pip install -r requirements.txt
```

**离线安装**（参见 `offline_packages/INSTALL.md`）：
```bash
pip install --no-index --find-links=offline_packages *.whl
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 配置

编辑 `config.json`：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "debug": false,
    "cors_origins": ["*"]
  },
  "ssh": {
    "default_port": 22,
    "timeout": 10,
    "keepalive_interval": 30
  },
  "database": {
    "path": "observation_web.db",
    "echo": false
  },
  "remote": {
    "agent_deploy_path": "/home/permitdir/observation_points",
    "agent_log_path": "/var/log/observation-points/alerts.log",
    "python_cmd": "python3"
  }
}
```

### 4. 启动服务

**后端**：
```bash
cd observation_web
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**前端开发服务器**：
```bash
cd frontend
npm run dev
```

**生产环境**（构建静态文件）：
```bash
cd frontend
npm run build
# dist 目录可部署到 Nginx
```

### 5. 访问

- 前端: http://localhost:5173 (开发) 或 http://localhost:3000 (生产)
- API 文档: http://localhost:8000/docs

## API 参考

### 阵列管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/arrays` | 获取阵列列表（仅数据库记录） |
| GET | `/api/arrays/statuses` | 获取阵列状态（含连接状态） |
| POST | `/api/arrays` | 添加阵列 |
| GET | `/api/arrays/{id}` | 获取单个阵列 |
| PUT | `/api/arrays/{id}` | 更新阵列 |
| DELETE | `/api/arrays/{id}` | 删除阵列 |
| POST | `/api/arrays/{id}/connect` | 连接阵列 |
| POST | `/api/arrays/{id}/disconnect` | 断开连接 |
| POST | `/api/arrays/{id}/refresh` | 刷新状态并同步告警 |
| GET | `/api/arrays/{id}/status` | 获取阵列详细状态 |

### Agent 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/arrays/{id}/deploy-agent` | 部署 Agent |
| POST | `/api/arrays/{id}/start-agent` | 启动 Agent |
| POST | `/api/arrays/{id}/stop-agent` | 停止 Agent |
| POST | `/api/arrays/{id}/restart-agent` | 重启 Agent |

### 告警管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/alerts` | 获取告警列表（支持过滤） |
| GET | `/api/alerts/recent` | 获取最近告警 |
| GET | `/api/alerts/stats` | 告警统计 |
| GET | `/api/alerts/summary` | 告警摘要 |

### 系统告警

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system-alerts` | 获取系统告警 |
| GET | `/api/system-alerts/stats` | 系统告警统计 |
| GET | `/api/system-alerts/debug` | 调试信息（SSH状态、缓存等） |
| DELETE | `/api/system-alerts` | 清空系统告警 |

### WebSocket

- `/ws/alerts` - 实时告警推送
- `/ws/status` - 阵列状态更新

## 功能说明

### AlarmType 告警处理

- `alarm type(0)`: 历史告警上报，仅通知，不加入活跃告警列表
- `alarm type(1)`: 事件生成
- `send alarm`: 告警上报（加入活跃告警）
- `resume alarm`: 告警恢复（从活跃告警移除）

### 自定义查询

支持三种匹配模式：

1. **有效值匹配**: 匹配到指定模式表示正常
2. **无效值匹配**: 匹配到指定模式表示异常
3. **正则提取**: 从输出中提取指定字段

示例：
```
命令: cat /proc/meminfo | grep MemFree
模式: MemFree:\s+(\d+)
类型: 正则提取
结果: 提取内存空闲值
```

### 系统调试

系统告警页面提供调试功能，可查看：
- SSH 连接状态
- 阵列状态缓存
- 告警统计
- 系统信息

## 测试用例

### 用例 1: 阵列管理

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 访问"阵列管理"页面 | 显示阵列列表（可能为空） |
| 2 | 点击"添加阵列"，填写表单 | 弹出添加对话框 |
| 3 | 输入有效的阵列信息，点击确定 | 阵列添加成功，列表更新 |
| 4 | 点击"连接"按钮，输入密码 | 连接成功，状态变为"已连接" |
| 5 | 点击"详情"查看阵列详情 | 显示阵列详细信息和观察点状态 |
| 6 | 点击"断开"按钮 | 断开成功，状态变为"未连接" |
| 7 | 点击"删除"按钮并确认 | 阵列删除成功 |

### 用例 2: Agent 部署

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 连接到阵列 | 连接成功 |
| 2 | 进入阵列详情页 | 显示 Agent 状态为"未部署" |
| 3 | 点击"部署 Agent" | 显示进度，部署完成后状态变为"已部署" |
| 4 | 点击"启动 Agent" | Agent 状态变为"运行中" |
| 5 | 点击"刷新" | 显示观察点状态和最近告警 |
| 6 | 点击"停止 Agent" | Agent 状态变为"已部署" |
| 7 | 点击"重启 Agent" | Agent 重新启动 |

### 用例 3: 告警查看

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 连接阵列并确保 Agent 运行 | 连接成功，Agent 运行中 |
| 2 | 点击阵列详情页"刷新" | 同步告警到本地数据库 |
| 3 | 访问"告警中心"页面 | 显示告警列表和统计 |
| 4 | 使用筛选器按级别过滤 | 只显示对应级别的告警 |
| 5 | 展开告警查看详情 | 显示告警详细信息 |
| 6 | 访问仪表盘 | 显示24小时告警趋势图 |

### 用例 4: 系统告警

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 访问"系统告警"页面 | 显示系统告警列表 |
| 2 | 展开调试信息 | 显示 SSH 连接状态、缓存信息 |
| 3 | 触发一个错误（如连接失败） | 系统告警列表新增错误记录 |
| 4 | 查看错误详情 | 显示错误堆栈和详细信息 |
| 5 | 点击"清空"按钮 | 清空所有系统告警 |

### 用例 5: 连接稳定性

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 连接到阵列 | 连接成功 |
| 2 | 等待一段时间（如5分钟） | 连接保持 |
| 3 | 返回阵列管理页面 | 阵列显示为"已连接" |
| 4 | 强制断开网络后恢复 | 自动重连（最多3次） |
| 5 | 检查系统告警 | 如有重连，显示相关告警 |

### 用例 6: 自定义查询

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 连接到阵列 | 连接成功 |
| 2 | 访问"自定义查询"页面 | 显示查询界面 |
| 3 | 输入命令 `hostname` | 执行成功，返回主机名 |
| 4 | 添加正则模式进行匹配 | 根据模式显示匹配结果 |
| 5 | 保存为查询模板 | 模板保存成功 |
| 6 | 选择保存的模板执行 | 使用模板参数执行查询 |

## 故障排查

### 问题: 连接阵列失败
- 检查网络连通性: `ping <array_ip>`
- 检查 SSH 端口: `telnet <array_ip> 22`
- 检查用户名密码是否正确
- 查看系统告警页面的错误详情

### 问题: 告警不同步
- 确保 Agent 已部署并运行
- 点击阵列详情页的"刷新"按钮手动同步
- 检查 `agent_log_path` 配置是否正确
- 查看系统告警中是否有读取文件的错误

### 问题: 页面卡住
- 检查后端服务是否正常运行
- 检查浏览器控制台是否有错误
- 尝试刷新页面
- 查看系统告警中的慢请求记录

### 问题: 阵列重启后数据丢失
- 数据库文件路径为相对路径，确保从固定目录启动服务
- 或在 `config.json` 中使用绝对路径配置数据库

## 更新日志

### v1.1.0
- 新增系统告警模块，支持错误追踪和调试
- 修复 `/api/arrays/statuses` 404 问题
- 修复数据库路径问题，使用绝对路径
- 优化告警同步，自动保存到数据库并 WebSocket 广播
- 优化 alarm type(0) 处理，标记为"历史告警上报"
- 添加 SSH 自动重连机制
- 优化前端请求超时处理
- 添加全局异常追踪中间件

### v1.0.0
- 初始版本
- 多阵列管理
- Agent 部署和管理
- 实时告警推送
- 自定义查询

## 许可证

MIT License
