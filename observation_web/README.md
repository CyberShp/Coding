# 观察点监控平台 - Web 版

基于 FastAPI + Vue 3 的存储阵列监控平台 Web 服务。

## 功能特性

- **多阵列管理**: 集中管理多台存储阵列
- **实时监控**: WebSocket 实时推送告警
- **自定义查询**: 灵活的命令执行和正则匹配
- **告警分析**: 告警统计、趋势分析
- **观察点监测**: 误码、链路状态、卡修复、内存泄漏等

## 技术栈

### 后端
- FastAPI (Python 3.6+)
- SQLite + SQLAlchemy
- Paramiko (SSH)
- WebSocket

### 前端
- Vue 3 + Vite
- Element Plus
- ECharts
- Pinia

## 目录结构

```
observation_web/
├── backend/                # FastAPI 后端
│   ├── main.py            # 应用入口
│   ├── config.py          # 配置管理
│   ├── api/               # API 路由
│   ├── core/              # 核心逻辑
│   ├── models/            # 数据模型
│   └── db/                # 数据库
├── frontend/              # Vue 3 前端
│   ├── src/
│   │   ├── views/        # 页面组件
│   │   ├── components/   # 通用组件
│   │   ├── api/          # API 封装
│   │   └── stores/       # 状态管理
│   └── package.json
├── config.json            # 配置文件
└── requirements.txt       # Python 依赖
```

## 快速开始

### 1. 安装后端依赖

```bash
cd observation_web
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 启动后端

```bash
# 在 observation_web 目录下
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm run dev
```

### 5. 访问

打开浏览器访问 http://localhost:3000

## API 文档

启动后端后，访问 http://localhost:8000/docs 查看 Swagger API 文档。

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/arrays` | 获取阵列列表 |
| POST | `/api/arrays` | 添加阵列 |
| POST | `/api/arrays/{id}/connect` | 连接阵列 |
| GET | `/api/alerts` | 获取告警列表 |
| GET | `/api/alerts/stats` | 告警统计 |
| POST | `/api/query/execute` | 执行自定义查询 |
| GET | `/api/query/templates` | 获取查询模板 |

## WebSocket

- `/ws/alerts` - 实时告警推送
- `/ws/status` - 阵列状态更新

## 自定义查询

支持三种匹配模式：

1. **有效值匹配**: 匹配到指定模式表示正常
2. **无效值匹配**: 匹配到指定模式表示异常
3. **正则提取**: 从输出中提取指定字段

示例：
```
命令: lsblk -o NAME,STATE
模式: running|online
类型: 有效值匹配
结果: 匹配到 "running" 或 "online" 表示正常
```

## 配置说明

`config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000
  },
  "ssh": {
    "default_port": 22,
    "timeout": 10
  },
  "remote": {
    "agent_path": "/opt/observation_points",
    "log_path": "/var/log/observation-points/alerts.log"
  }
}
```

## 许可证

MIT License
