# Observation Web Advance v2.0

**观察点监控平台 - Web 增强版 v2.0**

基于 FastAPI + Vue 3 的存储阵列观察点监控系统增强版，提供完善的告警管理、性能监控、数据生命周期、定时任务等功能。

## v2.0 新增功能

### 1. Agent 启动修复 (P0)
- 使用 PID 文件跟踪 Agent 进程，替代不可靠的 `nohup`
- 启动后验证进程存活（2 秒超时检测）
- 启动失败时返回详细错误日志（从 `/tmp/observation_points_start.log` 读取）
- 使用 `disown` 确保 SSH 断开后进程不被杀死

### 2. alerts.log 性能优化 (P0)
- **增量拉取**: 使用 `wc -l` + `tail -n` 只读取新增行，避免全量传输
- **位置记录**: 服务端追踪每个阵列的同步位置，支持断点续传
- **响应瘦身**: 刷新接口不再返回完整 `recent_alerts`，改为数据库分页查询
- **去重优化**: 从 O(n) DB 比对改为基于内容 hash 的内存去重

### 3. 双向数据推送 (P1)
- **Agent HTTP 推送**: Agent 可主动将告警推送到 Web 后端 `/api/ingest` 端点
- **指标推送**: CPU/内存等指标数据也可通过 HTTP 推送
- **异步推送**: 使用后台线程推送，不阻塞观察点检查
- **混合模式**: 推送和 SSH 拉取可并存，推送优先

### 4. CPU/内存性能曲线图 (P1)
- **Agent 指标采集**: CPU/内存观察点每次 check 都记录到 `metrics.jsonl`
- **指标 API**: 新增 `/api/arrays/{id}/metrics` 端点，支持时间范围查询
- **ECharts 可视化**: 阵列详情页新增"性能监控"卡片
  - CPU0 利用率折线图 + 90% 告警线
  - 内存使用量折线图
  - 支持 30分钟/1小时/6小时/24小时时间范围
  - 自动刷新（15 秒间隔）
  - 数据缩放（鼠标滚轮）

### 5. 界面功能化增强 (P1)
- **仪表盘健康矩阵**: 阵列卡片显示状态栏 + Agent 徽章 + 观察点状态点
- **观察点概览**: 按观察点维度统计正常/告警/错误比例
- **观察点卡片化**: 阵列详情中观察点从表格改为彩色卡片，直观展示状态
- **告警结构化展示**: AlarmType 告警解析为结构化表格（类型/名称/ID）
- **告警时间线**: 最近告警以时间线形式展示，支持历史告警标签

### 6. 50+ 台阵列规模优化 (P2)
- **异步 SSH 执行**: 新增 `execute_async` 方法，使用线程池避免阻塞事件循环
- **批量并发执行**: `SSHPool.batch_execute()` 支持在多台阵列上并发执行命令
- **空闲连接回收**: 后台任务每 2 分钟检测空闲超 10 分钟的连接并断开
- **连接统计**: `SSHPool.get_stats()` 提供连接池状态监控

### 7. 自定义监测固化 (P2)
- 查询模板新增"定时监测"开关
- 配置监测间隔（1分钟~1小时）
- 保存后自动注册为定时观察点
- 异常时自动生成告警并推送

### 8. 一键启动脚本 (P3)
- `start.sh` (Linux/Mac) 和 `start.bat` (Windows)
- 同时启动后端和前端服务
- 自动检测依赖并安装
- Ctrl+C 优雅停止所有服务

## 保留功能（v1.x）

- **数据导出**: 告警数据导出为 CSV 文件
- **数据生命周期管理**: 历史导入、归档转存、可配置保留期
- **在线日志查看器**: 远程日志实时查看、关键字搜索
- **批量操作**: 多选阵列批量连接/刷新/Agent 管理
- **定时任务**: Cron 调度查询任务
- **Agent 配置远程同步**: Web 端编辑远程 Agent 配置

## 快速开始

### 方式一：一键启动（推荐）

```bash
chmod +x start.sh
./start.sh
```

Windows:
```cmd
start.bat
```

### 方式二：手动启动

```bash
# 后端
pip install -r requirements.txt
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 前端（另一个终端）
cd frontend
npm install
npm run dev
```

### 离线安装

参见 [offline_packages/INSTALL.md](offline_packages/INSTALL.md)

## 目录结构

```
observation_web/
├── agent/                      # Agent 端（部署到存储阵列）
│   ├── __main__.py             # Agent 入口
│   ├── config.json             # Agent 默认配置
│   ├── core/                   # 核心模块（调度器、Reporter）
│   ├── observers/              # 观察点实现（20+ 个）
│   ├── config/                 # 配置加载器
│   └── utils/                  # 工具函数
├── backend/                    # FastAPI 后端（运行在本地 PC）
│   ├── api/
│   │   ├── arrays.py           # 阵列管理 + 批量操作 + 日志 + 指标
│   │   ├── alerts.py           # 告警管理 + 导出
│   │   ├── ingest.py           # 数据接收（Agent 推送）
│   │   ├── data_lifecycle.py   # 数据生命周期
│   │   ├── scheduler.py        # 定时任务
│   │   ├── websocket.py        # WebSocket 实时推送
│   │   └── system_alerts.py    # 系统告警
│   ├── core/
│   │   ├── agent_deployer.py   # Agent 部署（从 agent/ 打包上传）
│   │   ├── ssh_pool.py         # SSH 连接池（异步+回收）
│   │   ├── data_lifecycle.py   # 历史导入/归档
│   │   ├── scheduler.py        # APScheduler 任务调度
│   │   └── system_alert.py     # 系统告警存储
│   ├── models/                 # SQLAlchemy + Pydantic 模型
│   └── main.py                 # 入口 + 中间件 + 生命周期
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── views/
│   │   │   ├── Dashboard.vue          # 仪表盘（健康矩阵+观察点概览）
│   │   │   ├── ArrayDetail.vue        # 阵列详情（卡片+性能+结构化告警）
│   │   │   ├── CustomQuery.vue        # 自定义查询（含定时监测）
│   │   │   ├── DataManagement.vue     # 数据管理
│   │   │   ├── ScheduledTasks.vue     # 定时任务
│   │   │   └── ...
│   │   ├── components/
│   │   │   ├── PerformanceMonitor.vue # 性能监控（ECharts 曲线图）
│   │   │   ├── LogViewer.vue          # 日志查看器
│   │   │   └── AgentConfig.vue        # Agent 配置编辑器
│   │   └── api/index.js               # API 客户端
│   └── ...
├── start.sh                    # Linux/Mac 一键启动
├── start.bat                   # Windows 一键启动
├── offline_packages/           # 离线安装包
└── requirements.txt            # Python 依赖
```

> **注意**: `agent/` 目录在部署到阵列时会被打包为 `observation_points.tar.gz`，解压后目录名为 `observation_points`，以便 Python 模块导入正常工作。

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/arrays` | GET/POST | 阵列管理 |
| `/api/arrays/statuses` | GET | 阵列状态（含连接状态） |
| `/api/arrays/batch/{action}` | POST | 批量操作 |
| `/api/arrays/{id}/refresh` | POST | 增量刷新（含 full_sync 参数） |
| `/api/arrays/{id}/metrics` | GET | 性能指标（CPU/内存曲线） |
| `/api/arrays/{id}/logs` | GET | 远程日志查看 |
| `/api/arrays/{id}/agent-config` | GET/PUT | Agent 配置管理 |
| `/api/alerts` | GET | 告警查询 |
| `/api/alerts/export` | GET | 告警导出 (CSV) |
| `/api/ingest` | POST | 接收 Agent 推送数据 |
| `/api/ingest/batch` | POST | 批量接收推送数据 |
| `/api/data/*` | * | 数据生命周期 |
| `/api/tasks` | * | 定时任务 CRUD |
| `/api/system-alerts` | * | 系统告警 |
| `/ws/alerts` | WS | WebSocket 实时告警 |
| `/ws/status` | WS | WebSocket 状态更新 |

## Agent 配置（推送模式）

在阵列端的 `config.json` 中添加推送配置:

```json
{
  "reporter": {
    "output": "file",
    "file_path": "/var/log/observation-points/alerts.log",
    "push_enabled": true,
    "push_url": "http://192.168.1.100:8000/api/ingest",
    "push_timeout": 5,
    "metrics_enabled": true
  }
}
```

## 技术栈

**后端:**
- FastAPI + Uvicorn
- SQLAlchemy + aiosqlite
- Paramiko (SSH) + ThreadPoolExecutor
- APScheduler (定时任务)
- WebSocket (实时推送)

**前端:**
- Vue 3 + Vite
- Element Plus (UI 组件)
- ECharts + vue-echarts (数据可视化)
- Pinia (状态管理)
- Vue Router

## 系统要求

- Python 3.8+
- Node.js 16+
- 目标阵列支持 SSH 访问
- 阵列与 PC 之间网络可达（推送模式需要阵列能访问 PC 的 8000 端口）

## 许可证

MIT License
