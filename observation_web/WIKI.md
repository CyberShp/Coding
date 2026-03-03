# 存储阵列观察点监控系统 — 用户手册

> **版本**：4.0.0  
> **适用人群**：存储测试工程师、自动化测试平台维护人员  
> **最后更新**：2026-03-03

---

## 目录

1. [系统简介](#1-系统简介)
2. [系统架构](#2-系统架构)
3. [部署指南](#3-部署指南)
4. [功能详解](#4-功能详解)
   - 4.1 [仪表盘](#41-仪表盘)
   - 4.2 [阵列管理](#42-阵列管理)
   - 4.3 [告警中心](#43-告警中心)
   - 4.4 [测试任务管理](#44-测试任务管理)
   - 4.5 [事件时间线](#45-事件时间线)
   - 4.6 [状态快照与对比](#46-状态快照与对比)
   - 4.7 [端口流量监控](#47-端口流量监控)
   - 4.8 [性能监控（CPU / 内存）](#48-性能监控cpu--内存)
   - 4.9 [自定义查询](#49-自定义查询)
   - 4.10 [定时任务](#410-定时任务)
   - 4.11 [数据管理与归档](#411-数据管理与归档)
   - 4.12 [系统告警](#412-系统告警)
   - 4.13 [关键事件通知](#413-关键事件通知)
   - 4.14 [活跃告警与异常面板](#414-活跃告警与异常面板)
   - 4.15 [告警确认消除机制](#415-告警确认消除机制)
   - 4.16 [管理员登录](#416-管理员登录)
   - 4.17 [建议反馈](#417-建议反馈)
   - 4.18 [昵称身份系统](#418-昵称身份系统)
5. [观察点（Observer）完整列表](#5-观察点observer完整列表)
   - 5.1 [端口级观察点](#51-端口级观察点)
   - 5.2 [卡件级观察点](#52-卡件级观察点)
   - 5.3 [系统级观察点](#53-系统级观察点)
6. [告警体系](#6-告警体系)
   - 6.1 [告警级别](#61-告警级别)
   - 6.2 [告警三段式可读性](#62-告警三段式可读性)
   - 6.3 [告警聚合与风暴抑制](#63-告警聚合与风暴抑制)
   - 6.4 [告警智能折叠](#64-告警智能折叠)
7. [配置参考](#7-配置参考)
   - 7.1 [Web 端配置](#71-web-端配置)
   - 7.2 [Agent 端配置](#72-agent-端配置)
8. [规格与约束](#8-规格与约束)
9. [常见场景操作指南](#9-常见场景操作指南)
10. [故障排查](#10-故障排查)
11. [术语表](#11-术语表)
12. [开发者扩展指南：如何添加一个新的观察点](#十二开发者扩展指南如何添加一个新的观察点)
13. [开发者教程：修改监测命令/回显/预期结果/Web 显示](#十三开发者教程修改监测命令回显预期结果web-显示)
14. [升级与部署](#14-升级与部署)

---

## 1. 系统简介

**存储阵列观察点监控系统**是一套面向存储测试场景的轻量级监控工具，由两个核心组件构成：

| 组件 | 运行位置 | 职责 | 本地目录 |
|------|---------|------|---------|
| **Agent** | 存储阵列上 | 在阵列本地运行，周期性检查各项指标，输出告警日志 | `agent/` |
| **Web 平台** | 本地 PC / 测试服务器 | 管理阵列连接、采集告警数据、提供 Web 可视化界面 | `backend/` + `frontend/` |

> **项目结构**：Agent 和 Web 平台现已合并为统一项目。Agent 代码位于 `agent/` 目录，部署到阵列时会被打包为 `observation_points` 模块。

### 核心价值

- **测试场景感知**：支持创建测试任务，系统自动关联告警与测试上下文，区分"预期异常"和"真正问题"
- **关键事件聚焦**：进程崩溃、IO 超时、控制器离线等关键事件自动高亮，桌面通知+声音提醒，不被海量告警淹没
- **告警风暴抑制**：拔线/下电等操作触发的大量告警自动聚合为一条根因事件
- **全局时间线**：跨观察点的事件按时间轴展示，直观看到事件之间的先后关系
- **零外部依赖**：Agent 端仅依赖 Python 标准库，无需在阵列上安装任何第三方包

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    本地 PC / 测试服务器                  │
│                                                      │
│  ┌─────────────────┐    ┌──────────────────────────┐ │
│  │  前端 (Vue 3)    │◄──►│    后端 (FastAPI)         │ │
│  │  端口: 5173      │    │    端口: 9999             │ │
│  │  Element Plus    │    │    SQLite + SSH Pool     │ │
│  │  ECharts 图表    │    │    WebSocket 实时推送     │ │
│  └─────────────────┘    └──────────┬───────────────┘ │
│                                    │ SSH              │
└────────────────────────────────────┼─────────────────┘
                                     │
          ┌──────────────────────────┼──────────────────┐
          │                          │                   │
  ┌───────▼──────┐   ┌──────────────▼─┐   ┌────────────▼──┐
  │ 存储阵列 A    │   │  存储阵列 B     │   │  存储阵列 C    │
  │              │   │                │   │               │
  │  Agent       │   │  Agent         │   │  Agent        │
  │  (Python)    │   │  (Python)      │   │  (Python)     │
  │              │   │                │   │               │
  │  alerts.log  │   │  alerts.log    │   │  alerts.log   │
  │  traffic.jsonl│   │  traffic.jsonl │   │  traffic.jsonl│
  └──────────────┘   └────────────────┘   └───────────────┘
```

### 通信方式

- **PC → 阵列**：通过 SSH 连接（Paramiko 库），用于部署 Agent、启动/停止 Agent、拉取日志和流量数据
- **阵列 → PC**（可选）：Agent 可配置 HTTP 推送模式，将告警数据主动推送至 Web 后端的 `/api/ingest` 接口
- **告警双通道同步**：Agent HTTP push 为主通道；后端每 60 秒 SSH 定时拉取为兜底，确保告警实时性
- **前端 ↔ 后端**：HTTP REST API + WebSocket 实时告警推送

### 数据存储

- **阵列端**：`alerts.log`（JSON 格式告警日志）、`traffic.jsonl`（端口流量采集数据）
- **PC 端**：SQLite 数据库（`observation_web.db`），存储阵列信息、告警记录、定时任务、快照等

---

## 3. 部署指南

### 3.1 环境要求

#### 本地 PC（Web 平台）

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows / macOS / Linux 均可 |
| Python | 3.8 及以上 |
| Node.js | 16 及以上（用于前端开发服务器；生产模式可选） |
| 网络 | 能通过 SSH（默认 22 端口）连接到所有被监控阵列 |
| 磁盘空间 | 约 200 MB（含依赖） |

#### 存储阵列（Agent）

| 项目 | 要求 |
|------|------|
| 操作系统 | Euler ARM / CentOS / 通用 Linux |
| Python | 3.6 及以上（仅标准库，无需 pip） |
| 权限 | 需要 root 权限或可读 `/sys`、`/proc`、日志文件的用户 |
| 磁盘空间 | 约 5 MB（Agent 代码）+ 日志空间 |

### 3.2 阵列端部署（Agent）

Agent 可通过两种方式部署：

#### 方式一：通过 Web 界面一键部署（推荐）

1. 在 Web 平台添加阵列，填写 IP、端口、用户名
2. 点击「连接」，输入密码
3. 连接成功后，点击「部署 Agent」
4. 部署完成后，点击「启动 Agent」

> Agent 会被上传至阵列的 `/OSM/coffer_data/observation_points` 目录

#### 方式二：手动部署

```bash
# 1. 将 agent 目录复制到阵列（需重命名为 observation_points）
scp -r agent admin@阵列IP:/OSM/coffer_data/observation_points

# 2. 登录阵列
ssh admin@阵列IP

# 3. 创建日志目录
mkdir -p /var/log/observation-points

# 4. 编辑配置（按需修改 command 字段）
vi /OSM/coffer_data/observation_points/config.json

# 5. 启动 Agent
cd /OSM/coffer_data
python3 -m observation_points -c observation_points/config.json &
```

#### Agent 配置要点

以下观察点**需要手动填写命令**（因为不同阵列的管理命令不同）：

| 观察点 | config.json 中的字段 | 说明 |
|--------|---------------------|------|
| 卡件信息 (`card_info`) | `observers.card_info.command` | 查询所有卡件信息的命令 |
| 控制器状态 (`controller_state`) | `observers.controller_state.command` | 查询控制器状态的命令 |
| 磁盘状态 (`disk_state`) | `observers.disk_state.command` | 查询磁盘状态的命令 |

其他观察点（如误码、链路状态、FEC、PCIe 带宽等）使用**内置通用命令**（ethtool、sysfs、lspci），无需手动配置。

### 3.3 本地 PC 部署（Web 平台）

#### 一键启动

```bash
cd observation_web
bash start.sh
```

`start.sh` 会自动：
- 检查 Python 和 Node.js 版本
- 安装 Python 依赖（`pip install -r requirements.txt`）
- 安装前端依赖（`npm install`）
- 启动后端服务（默认端口 9999）
- 启动前端开发服务器（默认端口 5173）

启动成功后，浏览器访问：**http://localhost:5173**

#### 手动启动

```bash
# 后端
cd observation_web
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 9999

# 前端（另开终端）
cd observation_web/frontend
npm install
npm run dev
```

#### 生产模式部署

```bash
# 构建前端静态文件
cd observation_web/frontend
npm run build

# 启动后端（前端由后端静态服务或 Nginx 代理）
cd observation_web
python -m uvicorn backend.main:app --host 0.0.0.0 --port 9999
```

---

## 4. 功能详解

### 4.1 仪表盘

**路径**：`/`（首页）

仪表盘提供全局概览，包含：

- **统计卡片**（可点击跳转）：
  - 总阵列数 → 点击跳转到阵列管理
  - 在线阵列 → 点击跳转到阵列管理
  - 24 小时告警数 → 点击跳转到告警中心
  - 错误告警数 → 点击跳转到告警中心，并自动筛选错误级别
- **阵列健康矩阵**：彩色方块显示各阵列状态
  - 绿色 = 健康（无活跃问题）
  - 黄色 = 有 WARNING 级别活跃问题
  - 红色 = 有 ERROR/CRITICAL 级别活跃问题
  - 灰色 = 离线/未连接
  - 每个方块显示"X 个活跃问题"或"健康"标签
- **24 小时告警趋势**：折线图展示告警数量随时间的变化
- **实时告警流**：显示最新告警（含来源阵列名、确认按钮），支持智能折叠，点击可查看详情
- **活跃测试任务横幅**：如果有正在进行的测试任务，在统计卡片上方显示任务名称和已运行时间

### 4.2 阵列管理

**路径**：`/arrays`

管理所有被监控的存储阵列：

- **添加阵列**：填写名称、IP 地址、SSH 端口（默认 22）、用户名
- **连接阵列**：输入密码后 SSH 连接，密码保存在本地，断开后自动重连（最多 3 次）
- **批量操作**：支持批量连接、断开、刷新、部署 Agent、启动/停止 Agent
- **阵列详情页**：
  - 基本信息（连接状态、Agent 状态）
  - **活跃告警与异常面板**（仅显示当前未解决的问题，支持确认消除）
  - 最近告警（智能折叠、确认按钮、详情抽屉）
  - 性能监控（CPU/内存实时曲线）
  - 端口流量监控（TX/RX 带宽曲线，实时自动刷新）
  - 事件时间线（跨观察点时间轴视图）
  - 状态快照与对比
  - Agent 控制面板（部署/启动/停止/重启/配置修改）

**连接保持机制**：
- SSH keepalive 间隔：30 秒
- **SSH 心跳探活**：每次操作前发送 `send_ignore()` 轻量包检测连接真实可用性，避免假活导致的操作卡死
- 空闲连接自动清理：10 分钟无操作
- 自动重连：连接断开后最多尝试 3 次重连
- Agent 健康检查：每 5 分钟检测 Agent 是否仍在运行
- **刷新超时保护**：所有 SSH 操作均有 asyncio 层面的超时兜底，防止网络异常导致页面无限转圈

### 4.3 告警中心

**路径**：`/alerts`

集中管理所有阵列的告警信息：

- **筛选条件**：告警级别、观察点类型、时间范围（1 小时 / 6 小时 / 24 小时 / 7 天）
- **平铺模式**：传统列表视图，按时间倒序显示每条告警
- **聚合模式**：（通过右上角开关切换）
  - 时间窗口聚合：同一阵列同一观察点在 10 秒内触发的告警合并
  - 根因关联：link_down + FEC 变化 + 速率变化 自动聚合为「端口链路事件」
  - 风暴检测：60 秒内超过 20 条告警触发「告警风暴」摘要
- **告警来源阵列**：每条告警显示来自哪个阵列，方便跨阵列定位
- **告警确认**：每条告警可点击"确认"标记为非问题，已确认的显示绿色"已确认"徽章
- **告警详情抽屉**：点击任意告警，右侧弹出详情面板，展示：
  - 来源阵列名称
  - 三段式卡片：**事件**（发生了什么）→ **影响**（有什么后果）→ **建议**（该怎么处理）
  - 结构化信息（alarm_type 专有：AlarmId、objType、动作）
  - 告警确认区域（确认/撤销、确认人 IP、时间、备注）
  - 日志来源路径
  - 原始消息（可折叠）
  - 详细数据 JSON（可折叠）
- **导出**：支持导出为 CSV 文件（最多 10000 条）

### 4.4 测试任务管理

**路径**：`/test-tasks`

**设计目的**：让系统具备测试上下文感知能力，区分"测试引起的预期异常"和"真正的问题"。

**使用流程**：

1. **创建任务**：填写任务名称、选择测试类型、关联阵列
2. **开始任务**：点击「开始」，系统记录开始时间
3. **执行测试**：正常执行手工/自动化测试操作
4. **结束任务**：点击「结束」，系统自动：
   - 记录结束时间
   - 将时间窗口内的所有告警自动打上该任务标签（`task_id`）
   - 在事件时间线中用背景色标记该任务的时间段

**测试类型选项**：

| 类型 | 说明 |
|------|------|
| 正常业务 | 常规读写、业务功能测试 |
| 控制器下电 | 控制器下电/重启测试 |
| 接口卡下电 | 接口卡热插拔、下电测试 |
| 端口开关 | 端口 enable/disable 操作 |
| 线缆拔插 | 物理线缆拔插测试 |
| 系统故障注入 | 注入各类系统级故障 |
| 控制器升级 | 固件/系统升级（含下电步骤） |
| 自定义 | 其他类型 |

**任务摘要**：任务结束后可查看摘要报告，包含：
- 持续时长
- 各级别告警统计
- 各观察点告警统计
- 关键事件列表

### 4.5 事件时间线

**位置**：阵列详情页 → 事件时间线卡片

以散点图展示所有事件的时间分布：

- **X 轴**：时间
- **Y 轴**：观察点分类（端口级 / 卡件级 / 系统级）
- **颜色**：红 = 错误/严重，黄 = 警告，灰 = 信息
- **交互**：
  - 鼠标悬停显示事件详情
  - 支持鼠标滚轮缩放时间轴
  - 支持拖动平移
- **测试任务标记**：如有活跃测试任务，用蓝色半透明背景标记任务时间段
- **下方事件表格**：列出所有事件，方便快速浏览

**时间范围选择**：最近 1 小时 / 6 小时 / 24 小时 / 3 天

### 4.6 状态快照与对比

**位置**：阵列详情页 → 状态快照与对比卡片

**使用场景**：测试前拍一个快照，测试后再拍一个，对比两个快照发现状态差异。

- **拍摄快照**：捕获当前时刻各观察点的最新告警状态
- **快照列表**：显示该阵列的所有历史快照
- **对比功能**：勾选 2 个快照，点击「对比」，展示差异表格：
  - 绿色 = 新增的观察点
  - 红色 = 丢失的观察点
  - 黄色 = 状态发生变化的观察点
  - 显示变化前后的级别和消息

### 4.7 端口流量监控

**位置**：阵列详情页 → 端口流量监控卡片

实时展示端口 TX/RX 带宽曲线：

- **端口选择**：下拉选择要查看的端口
- **时间范围**：最近 5 分钟 / 10 分钟 / 30 分钟 / 1 小时 / 2 小时
- **曲线图**：双线（TX 发送 / RX 接收），鼠标悬停显示时间和带宽值
- **带宽单位自动适配**：b/s → Kb/s → Mb/s → Gb/s
- **数据同步**：点击「同步」按钮从阵列拉取最新流量数据

**数据保留策略**：
- 阵列端：`traffic.jsonl` 最多保留 2 小时数据，超时自动清理
- PC 端数据库：同步后也保留 2 小时，后台自动清理

### 4.8 性能监控（CPU / 内存）

**位置**：阵列详情页 → 性能监控卡片（需阵列已连接）

- 实时 CPU0 利用率曲线
- 实时内存使用率曲线
- 数据通过 SSH 定期采集，每次刷新时获取最新数据点

### 4.9 自定义查询

**路径**：`/query`

在已连接的阵列上执行自定义命令，支持：

- **命令输入**：输入要在阵列上执行的 shell 命令
- **规则匹配**：
  - 正则匹配：对输出做正则表达式检查
  - 关键字匹配：检查输出是否包含指定字符串
  - 字段提取：从输出中提取指定字段
- **查询模板**：保存常用查询为模板，下次一键执行
- **批量执行**：同时在多个阵列上执行同一查询

### 4.10 定时任务

**路径**：`/tasks`

配置周期性自动执行的查询任务：

- 关联查询模板
- Cron 表达式配置调度时间
- 查看历史执行结果
- 支持手动立即执行

### 4.11 数据管理与归档

**路径**：`/data`

- **数据导入**：手动导入历史告警数据
- **数据归档**：配置自动归档策略（保留天数，默认 30 天）
- **手动归档**：一键清理过期数据
- **归档统计**：查看已归档数据量

### 4.12 系统告警

**路径**：`/system-alerts`

显示系统自身的运行异常，而非阵列监控告警。包括：

- HTTP 请求异常（500 错误）
- 慢请求（响应超过 5 秒）
- SSH 连接失败
- Agent 异常停止
- 数据库错误

**用途**：当发现功能不正常时，优先查看系统告警定位问题。

### 4.13 关键事件通知

**全局功能**，无需进入特定页面：

- **红色横幅**：页面顶部固定显示，有未处理的关键事件时一直存在（带脉冲动画）
- **桌面通知**：使用浏览器 Notification API，关键事件触发时弹出桌面通知（需用户授权）
- **提示音**：可在页面右上角开关。开启后，关键事件触发时播放短促双音提示

**关键事件定义**：
- 进程崩溃（process_crash）
- IO 超时（io_timeout）
- SIG 异常信号（sig_monitor）
- 控制器状态异常（controller_state）
- 磁盘状态异常（disk_state）
- 所有 `critical` 级别告警

### 4.14 活跃告警与异常面板

**位置**：阵列详情页 → 顶部第一个面板

实时展示该阵列当前**仍未解决**的问题，仅在问题存在时显示条目，问题恢复后自动消失：

- **追踪的观察点类型**：
  | 观察点 | 出现条件 | 消失条件 |
  |--------|---------|---------|
  | CPU 利用率 | 连续超过 90% 阈值 | 降到 90% 以下 |
  | 内存泄漏 | 检测到内存持续增长 | 内存恢复正常 |
  | AlarmType:1 fault | 收到故障告警 | 收到对应 AlarmType:2 resume |
  | PCIe 带宽降级 | 检测到降速降 lane | 恢复正常速率 |
  | 卡件状态异常 | RunningState/HealthState 异常 | 恢复正常状态 |

- **与仪表盘联动**：
  - 仪表盘中阵列健康矩阵的颜色基于活跃问题数量判断
  - 0 个活跃问题 = 绿色（健康）
  - 有 WARNING 级别 = 黄色
  - 有 ERROR/CRITICAL 级别 = 红色
  - 显示"X 个活跃问题"标签

- **确认消除**：每个条目右侧有"确认消除"按钮（见 4.15）

### 4.15 告警确认消除机制

**全局功能**，可在以下三处使用：

1. **阵列详情页** → 活跃告警面板的"确认消除"按钮 / 最近告警的"确认"按钮
2. **仪表盘** → 实时告警流中的"确认"按钮
3. **告警中心** → 告警列表中的"确认"按钮

**功能说明**：

- **确认**：将告警标记为"已确认非问题"，已确认的告警：
  - 从活跃告警面板中消失
  - 在告警列表中显示绿色"已确认"徽章
  - 保留在告警中心和最近告警中可查看
  - 仪表盘阵列健康状态相应更新
- **批量确认**：对折叠的告警组点击"确认全组"，可一次确认组内所有未确认告警
- **撤销确认**：在告警详情抽屉中点击"撤销确认"，告警恢复为未确认状态
- **确认记录**：
  - 记录确认人的 **IP 地址**（区分不同使用者）
  - 记录确认时间
  - 支持填写备注说明
- **新告警不继承**：新产生的告警不会自动继承旧告警的已确认状态

### 4.16 管理员登录

**路径**：`/admin/login`（从设置页进入）

**设计理念**：管理员登录不是入口门槛，而是"权限提升"。普通用户可自由浏览仪表盘、阵列、告警等页面，仅在需要管理操作（修改 Issue 状态、系统设置等）时才需登录。

**登录入口**：设置页面（Settings）顶部「管理员登录」按钮

**登录页交互**：左侧 3 只像素风格宠物 SVG，右侧登录表单。5 种动画状态：闲逛、凝视、捂眼、错愕、欢呼

**默认账号**：`admin` / `admin123`（可在 `config.json` 的 `admin` 段修改）

**需要管理员权限的操作**：Issue 状态变更、系统设置修改

### 4.17 建议反馈

**路径**：`/issues`

**功能**：提交建议/反馈，按状态分类（待处理 / 已解决 / 不解决 / 已采纳）

**状态变更**：仅创建者（按 IP 或昵称）和管理员可操作

**侧边栏入口**：「建议反馈」菜单项

### 4.18 昵称身份系统

**首次访问**：弹出昵称设置对话框，用户输入昵称后作为主标识

**身份设计**：昵称为主标识、IP 为辅助。在线用户以昵称显示

**IP 变化恢复**：当用户 IP 变化（如换网络）后，可通过「认领昵称」恢复身份，系统自动迁移旧 IP 的会话数据、阵列锁定等到新 IP

---

## 5. 观察点（Observer）完整列表

系统共包含 **23 个观察点**，分为端口级、卡件级、系统级三类。

### 5.1 端口级观察点

| 观察点 | 名称 | 监控内容 | 命令来源 | 默认间隔 | 告警级别 |
|--------|------|---------|---------|---------|---------|
| `error_code` | 误码监测 | 端口 CRC/FCS/帧错误计数增量，PCIe AER 错误 | 内置（sysfs + ethtool） | 30s | WARNING |
| `link_status` | 链路状态 | 端口 carrier/operstate 变化（UP/DOWN） | 内置（sysfs） | 5s | WARNING |
| `port_fec` | FEC 模式 | FEC 编码模式是否发生变化 | 内置（ethtool --show-fec） | 60s | WARNING |
| `port_speed` | 端口速率 | 端口链接速率是否发生变化（如 25G → 10G） | 内置（sysfs / ethtool） | 60s | WARNING |
| `port_traffic` | 端口流量 | TX/RX 字节数采集，计算带宽速率 | 内置（sysfs statistics） | 30s | 无告警（仅采集数据） |
| `port_error_code` | 端口误码 | anytest portallinfo + portgeterr，0x2 以太网/0x11 FC 卡件误码统计 | 内置（anytest） | 60s | WARNING |

### 5.2 卡件级观察点

| 观察点 | 名称 | 监控内容 | 命令来源 | 默认间隔 | 告警级别 |
|--------|------|---------|---------|---------|---------|
| `card_recovery` | 卡修复 | 日志中的 recover chiperr 事件 | 内置（读取日志） | 30s | ERROR |
| `card_info` | 卡件信息 | RunningState / HealthState / Model 状态检查 | **需用户提供命令** | 120s | ERROR / WARNING |
| `pcie_bandwidth` | PCIe 带宽 | LnkCap vs LnkSta 对比，检测降级 | 内置（lspci -vvv） | 120s | WARNING |
| `controller_state` | 控制器状态 | 控制器在线/离线/降级状态变化 | **需用户提供命令** | 60s | ERROR（持续） |
| `disk_state` | 磁盘状态 | 磁盘在线/离线/重建/故障状态变化 | **需用户提供命令** | 60s | ERROR / WARNING（持续） |
| `sfp_monitor` | 光模块监控 | anytest sfpallinfo，温度/健康/运行状态/FC 速率一致性 | 内置（anytest） | 120s | WARNING |

### 5.3 系统级观察点

| 观察点 | 名称 | 监控内容 | 命令来源 | 默认间隔 | 告警级别 |
|--------|------|---------|---------|---------|---------|
| `alarm_type` | 告警事件 | `/OSM/log/cur_debug/system_alarm.txt` 中的 AlarmType:0/1/2 事件 | 内置（读取日志） | 30s | WARNING（type 1/2）/ INFO（type 0） |
| `memory_leak` | 内存监测 | 内存使用率连续上升检测 | 内置（free -m） | 5400s（1.5h） | ERROR（持续） |
| `cpu_usage` | CPU 监测 | CPU0 利用率超阈值检测 | 内置（/proc/stat） | 30s | ERROR（持续） |
| `cmd_response` | 命令响应 | 命令执行耗时是否超过阈值 | 用户配置命令列表 | 60s | ERROR |
| `sig_monitor` | SIG 信号 | 日志中的异常信号事件 | 内置（读取日志） | 30s | ERROR |
| `sensitive_info` | 敏感信息 | 日志中是否泄露密码/密钥等敏感信息 | 内置（读取日志） | 30s | ERROR |
| `process_crash` | 进程崩溃 | segfault / core dump / OOM 等崩溃事件 | 内置（日志 + dmesg） | 30s | CRITICAL（持续） |
| `io_timeout` | IO 超时 | IO timeout / SCSI error 等存储 IO 异常 | 内置（日志 + dmesg） | 30s | ERROR / CRITICAL（持续） |
| `custom_commands` | 自定义命令 | 用户自定义的监测命令和预期结果 | 用户配置 | 自定义 | WARNING |
| `process_restart` | 进程拉起 | ps -aux 中 -v N 参数变化，检测进程被重拉 | 内置（ps） | 30s | WARNING |
| `abnormal_reset` | 异常复位 | os_cli cat log_reset.txt，检测异常复位原因 | 内置（os_cli） | 120s | WARNING |

> **"持续"标记**：该观察点触发告警后，不受冷却时间限制，每次检查都会上报，直到异常恢复。

### 观察点详细说明

#### card_info（卡件信息）

**需要用户填写命令**。在 `config.json` 的 `observers.card_info.command` 字段中填入查询所有卡件信息的命令。

命令回显格式要求：
```
No001  BoardId: 03024GRH
No001  Name: CX916
No001  Model: CX916
No001  RunningState: RUNNING
No001  HealthState: NORMAL
------------------
No002  BoardId: 03024GRJ
No002  Name: CX920
No002  RunningState: STOPPED
No002  HealthState: FAULT
```

解析规则：
- 卡件之间用 `---` 横线分隔
- 每行格式：`No编号  字段名<分隔符>值`
- 分隔符支持：`:`、`=`、`🟰`、空格
- 告警条件：RunningState ≠ RUNNING → ERROR，HealthState ≠ NORMAL → ERROR，Model 为空 → WARNING

#### controller_state（控制器状态）

**需要用户填写命令**。填入查询控制器状态的命令，回显需包含控制器标识和状态关键字。

#### disk_state（磁盘状态）

**需要用户填写命令**。填入查询磁盘状态的命令，回显需包含磁盘标识和状态关键字。

#### process_crash（进程崩溃）

自动扫描以下关键字（无需配置）：
- `segfault at` — 段错误
- `core dumped` — 核心转储
- `Out of memory...Killed process` — OOM 杀进程
- `general protection fault` — 通用保护错误
- `kernel BUG at` — 内核 BUG
- `Oops:` — 内核 Oops

#### io_timeout（IO 超时）

自动扫描以下关键字（无需配置）：
- `I/O error` — IO 错误
- `io timeout` — IO 超时
- `scsi error` — SCSI 错误
- `Medium Error` — 介质错误
- `Hardware Error` — 硬件错误
- `task abort` — 任务中止
- `device offline` — 设备离线
- `Buffer I/O error` — 缓冲区 IO 错误
- `EXT4-fs error` / `XFS error` — 文件系统错误

#### port_error_code（端口误码）

使用 `anytest portallinfo -t 2` 获取端口列表（0x2 以太网卡件、0x11 FC 卡件），对每个端口执行 `anytest portgeterr -p {port_id} -n 0`。0x11 卡件解析 LossOfSignal Count、BadRXChar Count 等；0x2 卡件解析 Rx Errors、Tx Errors、Rx Dropped、Tx Dropped、Collisions。非零即上报告警。

#### sfp_monitor（光模块监控）

使用 `anytest sfpallinfo` 获取光模块信息，按 `---+` 分隔为块。解析 PortId、parentID、Name、TempReal、HealthState、RunningState、RunSpeed、MaxSpeed。温度 ≥ 105°C 上报；HealthState 非 NORMAL 上报；RunningState 非 LINK_UP 上报；FC 光模块 MaxSpeed ≠ RunSpeed 或 RunSpeed 为 unknown 上报降速告警。

#### process_restart（进程拉起）

默认监控 `app_data`、`devm`、`memf` 三个进程（可配置）。每周期执行 `ps -aux | grep` 解析 `-v N` 参数。若 `-v` 值增大（如 1 → 2），说明进程被重拉，上报告警。

#### abnormal_reset（异常复位）

执行 `os_cli "cat ./log_reset.txt"` 获取复位日志，解析 reason 和 time。匹配异常关键字（watchDog reset、oops reset、unknown reset、oom reset、panic reset、kernel reset、mce reset、bios reset、software unknown reset、failure recovery reset）则上报告警，记录已上报时间戳避免重复。

---

## 6. 告警体系

### 6.1 告警级别

| 级别 | 颜色 | 含义 | 典型场景 |
|------|------|------|---------|
| INFO（信息） | 灰色 | 正常状态记录 | CPU 正常、历史告警上报 |
| WARNING（警告） | 黄色 | 需要关注但不紧急 | 误码增长、FEC 变化、端口速率变化 |
| ERROR（错误） | 红色 | 需要处理的问题 | 卡件异常、命令超时、内存持续增长 |
| CRITICAL（严重） | 深红色 | 需要立即处理 | 进程崩溃、大量 IO 超时 |

### 6.2 告警三段式可读性

每条告警翻译为三个部分：

| 部分 | 含义 | 示例 |
|------|------|------|
| **事件** | 发生了什么 | eth2 链路断开 |
| **影响** | 有什么后果 | 该端口业务中断，依赖该端口的 IO 将受到影响 |
| **建议** | 该怎么处理 | 检查线缆连接，确认是否为计划操作（拔线/下电测试） |

告警详情面板中，三个部分用不同颜色标记：
- 事件 → 红色标签
- 影响 → 黄色标签
- 建议 → 绿色标签

### 6.3 告警聚合与风暴抑制

#### 告警双通道同步

- **Agent 推送**：配置 `remote.ingest_url` 后，Agent 将告警主动推送至后端 `/api/ingest`
- **后端兜底**：每 60 秒对已连接阵列执行 SSH 拉取，确保告警实时性

#### 时间窗口聚合

同一阵列、同一观察点在 **10 秒**内触发的多条告警，自动合并为一条，显示「XX 秒内连续触发 N 次」。

#### 根因关联

| 触发条件 | 聚合结果 |
|---------|---------|
| link_status DOWN + port_fec 变化 + port_speed 变化 + error_code 增长（同一端口，30 秒内） | 聚合为「端口 ethX 链路事件（N 项关联告警）」 |
| card_info 异常 + pcie_bandwidth 降级 + card_recovery（同一卡件，30 秒内） | 聚合为「卡件 NoXXX 异常事件（N 项关联告警）」 |

#### 风暴检测

当同一阵列在 **60 秒**内产生超过 **20 条**告警时，触发风暴模式：
- 所有告警合并为一条风暴摘要
- 展示为醒目的黄色聚合卡片
- 点击可展开查看所有子告警

### 6.4 告警智能折叠

除了聚合模式外，告警列表在所有视图（仪表盘、阵列详情、告警中心）均支持**智能折叠**：

| 观察点 | 折叠依据（语义身份） | 示例 |
|--------|---------------------|------|
| `alarm_type` | `objType` + `action`（fault/resume） | 同一 DiskEnclosure 的多次 fault 折叠为一组 |
| `card_info` | `card编号` + `board_id` + `字段名` | No001 的 RunningState 多次告警折叠 |
| `error_code` | 端口名 | eth2 的多次误码增长折叠 |
| `link_status` | 端口名 | eth3 的多次 UP/DOWN 折叠 |
| 其他 | 消息骨架（去除数字/时间戳后的文本） | 相似消息自动合并 |

折叠组展示：
- 组头显示最新一条告警和总数
- 点击可展开查看组内所有告警
- "确认全组"按钮可批量确认
- 全部已确认的组显示"全部已确认"标签

---

## 7. 配置参考

### 7.1 Web 端配置

配置文件：`observation_web/config.json`

```json
{
  "admin": {
    "username": "admin",       // 管理员账号（用于 Issue 状态变更、系统设置等）
    "password": "admin123"     // 管理员密码，生产环境请修改
  },
  "server": {
    "host": "0.0.0.0",        // 监听地址
    "port": 9999,              // 后端端口
    "debug": false,            // 调试模式
    "cors_origins": ["*"]      // 跨域允许源
  },
  "ssh": {
    "default_port": 22,        // SSH 默认端口
    "timeout": 10,             // SSH 连接超时（秒）
    "keepalive_interval": 30   // SSH keepalive 间隔（秒）
  },
  "database": {
    "path": "observation_web.db",  // 数据库文件路径
    "echo": false                   // 是否输出 SQL 日志
  },
  "remote": {
    "agent_deploy_path": "/OSM/coffer_data/observation_points",  // Agent 部署路径
    "agent_log_path": "/var/log/observation-points/alerts.log",  // Agent 告警日志路径
    "python_cmd": "python3",                                     // 阵列上的 Python 命令
    "ingest_url": ""                                             // Agent 推送地址，如 http://192.168.1.100:9999/api/ingest
  }
}
```

### 7.2 Agent 端配置

配置文件：阵列上 `observation_points/config.json`

**完整配置示例**（含所有观察点，注释说明）：

```json
{
  "global": {
    "check_interval": 30,         // 全局检查间隔（秒），各观察点可独立设置
    "max_memory_mb": 50,          // Agent 最大内存限制（MB）
    "subprocess_timeout": 10       // 子进程执行超时（秒）
  },
  "reporter": {
    "output": "file",              // 输出方式：file / syslog / both / console
    "file_path": "/var/log/observation-points/alerts.log",
    "cooldown_seconds": 300        // 相同告警冷却时间（秒），持续告警不受此限制
  },
  "observers": {
    "error_code": {
      "enabled": true,
      "interval": 30,
      "threshold": 0,              // 误码增量超过此值才告警，0=任何增量
      "ports": []                  // 留空=自动发现所有端口
    },
    "link_status": {
      "enabled": true,
      "interval": 5                // 链路状态检测频率较高
    },
    "alarm_type": {
      "enabled": true,
      "interval": 30,
      "log_path": "/OSM/log/cur_debug/system_alarm.txt"
    },
    "cpu_usage": {
      "enabled": true,
      "interval": 30,
      "threshold_percent": 90,     // CPU 利用率阈值
      "consecutive_threshold": 6   // 连续 6 次超阈值才告警（= 3 分钟）
    },
    "memory_leak": {
      "enabled": true,
      "interval": 5400,            // 1.5 小时检查一次
      "consecutive_threshold": 8   // 连续 8 次增长才告警（= 12 小时）
    },
    "port_fec": {
      "enabled": true,
      "interval": 60
    },
    "port_speed": {
      "enabled": true,
      "interval": 60
    },
    "pcie_bandwidth": {
      "enabled": true,
      "interval": 120
    },
    "card_info": {
      "enabled": true,
      "interval": 120,
      "command": "",                // ← 必须填写，查询卡件信息的命令
      "running_state_expect": "RUNNING",
      "health_state_expect": "NORMAL"
    },
    "port_traffic": {
      "enabled": true,
      "interval": 30,
      "retention_hours": 2         // 本地流量数据保留 2 小时
    },
    "controller_state": {
      "enabled": true,
      "interval": 60,
      "command": ""                // ← 必须填写，查询控制器状态的命令
    },
    "disk_state": {
      "enabled": true,
      "interval": 60,
      "command": ""                // ← 必须填写，查询磁盘状态的命令
    },
    "process_crash": {
      "enabled": true,
      "interval": 30               // 无需填写命令，自动扫描系统日志
    },
    "io_timeout": {
      "enabled": true,
      "interval": 30               // 无需填写命令，自动扫描系统日志
    },
    "sig_monitor": {
      "enabled": true,
      "interval": 30,
      "whitelist": [15, 61]        // 忽略的信号编号
    },
    "sensitive_info": {
      "enabled": true,
      "interval": 30
    },
    "cmd_response": {
      "enabled": true,
      "interval": 60,
      "timeout_seconds": 1,        // 命令执行超过此时间即告警
      "commands": ["lscpu"]        // 要监测执行时间的命令列表
    },
    "port_error_code": {
      "enabled": true,
      "interval": 60,
      "command_list_ports": "anytest portallinfo -t 2",
      "command_get_errors": "anytest portgeterr -p {port_id} -n 0"
    },
    "process_restart": {
      "enabled": true,
      "interval": 30,
      "processes": ["app_data", "devm", "memf"]
    },
    "sfp_monitor": {
      "enabled": true,
      "interval": 120,
      "command": "anytest sfpallinfo",
      "temp_threshold": 105
    },
    "abnormal_reset": {
      "enabled": true,
      "interval": 120,
      "command": "os_cli \"cat ./log_reset.txt\"",
      "abnormal_reasons": ["watchDog reset", "oops reset", "unknown reset", "oom reset", "panic reset", "kernel reset", "mce reset", "bios reset", "software unknown reset", "failure recovery reset"]
    }
  }
}
```

---

## 8. 规格与约束

### 8.1 阵列规模

| 规格项 | 推荐值 | 最大值 | 说明 |
|--------|--------|--------|------|
| 同时管理阵列数 | ≤ 20 台 | 50 台 | 超过 20 台建议增大 SSH 线程池（当前 20 线程） |
| 同时在线（已连接）阵列数 | ≤ 15 台 | 30 台 | 每台阵列占用 1 个 SSH 长连接 |
| 单阵列告警量 | ≤ 500 条/天 | 不限 | 超过此量建议缩短归档周期 |
| 总告警存储量 | ≤ 10 万条 | 约 50 万条 | SQLite 在大数据量下查询可能变慢 |

### 8.2 性能影响

| 操作 | 耗时预期 | 影响因素 |
|------|---------|---------|
| 刷新阵列状态 | 2-10 秒 | SSH 延迟、告警日志大小 |
| 加载告警列表 | < 1 秒 | 数据量、筛选条件 |
| 同步流量数据 | 1-3 秒 | 流量数据文件大小 |
| 拍摄快照 | < 1 秒 | 数据库查询 |
| 部署 Agent | 5-15 秒 | SSH 传输速度 |

### 8.3 超过推荐规模的影响

当连接阵列数超过 20 台时：
- **SSH 线程池饱和**：并发操作（批量刷新、批量部署）可能排队等待
- **刷新延迟增大**：单次全量刷新可能需要更长时间
- **前端页面稍慢**：仪表盘需要加载更多阵列状态

**缓解措施**：
- 不经常使用的阵列可断开连接，需要时再连接
- 使用筛选条件减少告警加载量
- 适当延长非关键观察点的检查间隔

### 8.4 Agent 资源占用

| 指标 | 目标值 |
|------|--------|
| 内存占用 | < 50 MB |
| CPU 占用 | < 2%（单核） |
| 磁盘写入 | < 1 MB/小时（告警日志） |
| 网络流量 | 仅本地操作，不主动联网 |

### 8.5 数据保留策略

| 数据类型 | 默认保留时间 | 可配置 |
|---------|-------------|--------|
| 告警记录 | 30 天 | 是（数据管理 → 归档配置） |
| 端口流量数据 | 2 小时 | 是（Agent config.json） |
| 快照 | 不自动删除 | 手动管理 |
| 系统告警 | 内存中最多 500 条 | 否 |

### 8.6 约束与限制

1. **不支持 root 直接登录的阵列**：如果阵列禁止 root SSH 登录，使用 admin 等普通用户即可。Agent 启动后可能需要 sudo 权限访问部分 sysfs 文件
2. **单数据库限制**：使用 SQLite 单文件数据库，不适合多人同时写入的场景。如果需要多用户部署，建议每人独立运行一套
3. **SSH 密码不加密存储**：为了支持自动重连，密码保存在内存中，服务重启后需要重新输入
4. **不支持 HTTPS**：当前为 HTTP 服务，仅建议在内网环境使用
5. **需要用户填写的命令**：`card_info`、`controller_state`、`disk_state` 三个观察点需要根据阵列型号手动填写查询命令

---

## 9. 常见场景操作指南

### 场景一：正常业务测试

1. 仪表盘确认阵列在线、Agent 运行中
2. 创建测试任务：类型选「正常业务」，关联目标阵列
3. 点击「开始」
4. 执行测试操作
5. 测试完成后点击「结束」
6. 查看任务摘要，关注是否有非预期告警

### 场景二：控制器下电测试

1. 测试前：在阵列详情页点击「拍摄快照」保存基线状态
2. 创建测试任务：类型选「控制器下电」
3. 开始任务 → 执行下电操作
4. 观察：
   - 事件时间线：看到 controller_state 变为 offline
   - 可能触发的关联告警：link_status DOWN、error_code 增长
   - 告警聚合会自动归类
5. 控制器上电恢复后：
   - 观察 controller_state 恢复为 online
   - 再拍一个快照
   - 对比两个快照，确认所有状态恢复
6. 结束任务，查看摘要

### 场景三：线缆拔插测试

1. 创建测试任务：类型选「线缆拔插」
2. 开始任务
3. 拔线后预期告警（聚合为一条）：
   - link_status：ethX DOWN
   - port_fec：FEC 模式变化
   - port_speed：速率变化
   - error_code：误码增长
4. 插线后观察恢复
5. 关注：是否有非预期的 process_crash 或 io_timeout

### 场景四：长时间稳定性测试

1. 创建测试任务：类型选「正常业务」，备注测试时长
2. 开始任务
3. 定期检查仪表盘和告警中心
4. 重点关注：
   - memory_leak：内存是否持续增长
   - cpu_usage：CPU 是否持续高负载
   - process_crash：是否有进程崩溃
   - io_timeout：是否有 IO 超时
5. 测试结束后查看任务摘要

### 场景五：发现问题后的排查流程

1. 在告警中心看到红色告警
2. 点击告警查看详情：
   - **事件**：确认发生了什么
   - **影响**：了解影响范围
   - **建议**：按照建议操作
3. 如果有关联告警，切换到聚合模式查看根因
4. 在事件时间线中查看事件前后还发生了什么
5. 如果需要对比状态变化，使用快照对比
6. 如果是系统自身问题，查看系统告警页面

---

## 10. 故障排查

### 10.1 Web 平台无法启动

| 问题 | 排查方法 |
|------|---------|
| 端口被占用 | `lsof -i :9999` 或 `netstat -tlnp \| grep 9999`，终止占用进程或修改端口 |
| Python 依赖缺失 | `pip install -r requirements.txt` |
| Node.js 依赖缺失 | `cd frontend && npm install` |
| 数据库损坏 | 删除 `observation_web.db` 文件，重启后自动重建（数据将丢失） |

### 10.2 无法连接阵列

| 问题 | 排查方法 |
|------|---------|
| SSH 超时 | 确认 PC 能 ping 通阵列 IP |
| 认证失败 | 检查用户名和密码是否正确 |
| 连接频繁断开 | 检查网络稳定性，确认防火墙未拦截 SSH |

### 10.3 Agent 无法启动

| 问题 | 排查方法 |
|------|---------|
| Python 版本不够 | `python3 --version`，需 3.6+ |
| 权限不足 | 确认有 /var/log/observation-points 目录的写权限 |
| config.json 格式错误 | 用 `python3 -m json.tool config.json` 检查 JSON 格式 |

### 10.4 告警不同步

| 问题 | 排查方法 |
|------|---------|
| 阵列上 alerts.log 为空 | 确认 Agent 正在运行（`ps aux \| grep observation`） |
| PC 端看不到告警 | 点击阵列详情的「刷新」按钮手动同步 |
| 告警延迟 | 检查 SSH 连接是否正常，网络延迟是否过大 |
| 告警不实时 | 配置 `config.json` 中 `remote.ingest_url` 启用 Agent 推送；后端每 60 秒 SSH 定时同步为兜底，检查 alert_sync 日志 |

### 10.5 页面卡顿

| 问题 | 排查方法 |
|------|---------|
| 告警数据量过大 | 缩短筛选时间范围，执行数据归档清理 |
| 阵列数过多 | 断开不需要实时监控的阵列 |
| 浏览器内存不足 | 刷新页面，关闭其他标签页 |

---

## 11. 术语表

| 术语 | 说明 |
|------|------|
| **Agent** | 运行在存储阵列上的监控进程（observation_points），负责采集数据和生成告警 |
| **观察点（Observer）** | 一个独立的监控检查项，如误码监测、链路状态等 |
| **告警（Alert）** | 观察点检查发现异常时生成的通知 |
| **sticky 告警** | 持续告警，触发后每次检查都上报，不受冷却时间限制，直到异常恢复 |
| **冷却时间（Cooldown）** | 同一告警的抑制时间，默认 5 分钟内不重复上报（sticky 告警除外） |
| **告警风暴** | 短时间内大量告警涌入的情况，系统会自动合并为摘要 |
| **测试任务** | 一次测试活动的时间窗口，系统自动将该时间段内的告警与任务关联 |
| **快照** | 某一时刻阵列所有观察点状态的完整记录，用于前后对比 |
| **SSH Pool** | SSH 连接池，管理和复用与各阵列的 SSH 连接 |
| **FEC** | Forward Error Correction，前向纠错编码，用于网络端口数据传输纠错 |
| **PCIe** | Peripheral Component Interconnect Express，高速串行计算机扩展总线标准 |
| **LnkCap / LnkSta** | PCIe 链路能力 / 链路状态，用于检测 PCIe 降级 |
| **OOM** | Out of Memory，操作系统因内存不足而杀死进程 |
| **SCSI Error** | Small Computer System Interface 错误，存储 IO 通道异常 |
| **sysfs** | Linux 虚拟文件系统（/sys），提供硬件信息读取接口 |
| **ethtool** | Linux 网络驱动和硬件设置查询工具 |
| **lspci** | Linux PCI 设备列表查询工具 |
| **活跃问题** | 当前仍未解决的告警或异常状态，显示在阵列详情的活跃告警面板中 |
| **告警确认（Ack）** | 用户手动标记某条告警为"已确认非问题"，将其从活跃面板移除 |
| **昵称身份** | 用户以昵称为主标识，IP 为辅助；IP 变化后可认领昵称恢复身份 |
| **管理员登录** | 权限提升入口，用于 Issue 状态变更、系统设置等管理操作 |
| **迁移脚本** | `backend/db/migrations/` 下的版本化数据库变更脚本，启动时自动执行 |
| **智能折叠** | 基于语义身份（观察点+关键字段）将相似告警自动分组显示 |
| **AlarmType** | 阵列系统告警类型。0=事件（INFO）、1=故障（WARNING）、2=恢复（WARNING） |
| **send_ignore** | SSH 协议中的轻量心跳包，用于检测连接真实可用性 |

---

## 附录：快速参考卡

### 默认端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Web 后端 API | 9999 | FastAPI 服务 |
| 前端开发服务器 | 5173 | Vite 开发模式 |
| SSH 连接 | 22 | 连接存储阵列 |
| WebSocket | 9999 | 与后端同端口，路径 /ws/alerts |

### 管理员默认账号

| 项目 | 默认值 |
|------|--------|
| 账号 | admin |
| 密码 | admin123 |

### 默认文件路径

| 文件 | 位置 | 说明 |
|------|------|------|
| Web 配置 | `observation_web/config.json` | Web 平台配置 |
| Agent 配置 | 阵列上 `config.json` | Agent 端配置 |
| 告警日志 | 阵列上 `/var/log/observation-points/alerts.log` | Agent 输出的告警 |
| 流量数据 | 阵列上 `/var/log/observation-points/traffic.jsonl` | 端口流量采集 |
| 数据库 | `observation_web/observation_web.db` | SQLite 数据库 |

### 快捷键 / 快捷操作

| 操作 | 方法 |
|------|------|
| 快速查看错误告警 | 仪表盘点击「错误告警」数字 |
| 对比测试前后状态 | 阵列详情 → 测试前拍快照 → 测试后拍快照 → 对比 |
| 查看告警根因 | 告警中心 → 切换到「聚合」模式 |
| 查看事件先后关系 | 阵列详情 → 事件时间线 |
| 创建测试上下文 | 侧栏「测试任务」→ 创建 → 开始 |

---

## 十二、开发者扩展指南：如何添加一个新的观察点

本章面向希望仿写新观察点并接入系统的开发者。假设你已编写好一个新的观察点 Python 文件（例如 `my_observer.py`），以下是将其集成进系统所需修改的**全部文件清单**和**操作步骤**。

### 12.1 涉及文件总览

需要手动修改的文件共 **5 个**（Agent 端 3 个 + Web 端 2 个为可选），另有 1 个配置文件：

| 序号 | 文件路径 | 必须/可选 | 作用 |
|------|----------|-----------|------|
| 1 | `agent/observers/my_observer.py` | **必须** | 观察点实现文件（你编写的） |
| 2 | `agent/observers/__init__.py` | **必须** | 注册导出，让模块能被发现 |
| 3 | `agent/core/scheduler.py` | **必须** | 调度器映射，让调度器知道名称对应哪个类 |
| 4 | `agent/config/loader.py` | **必须** | 默认配置，确保即使用户 config.json 未配置也有兜底 |
| 5 | `agent/config.json` | **必须** | 用户配置文件，添加你的观察点配置项 |
| 6 | `frontend/src/utils/alertTranslator.js` | 可选(推荐) | Web 前端告警翻译，让告警以可读中文显示 |
| 7 | `backend/core/alert_aggregator.py` | 可选 | 告警聚合规则，如果需要与其他观察点做根因关联 |

### 12.2 步骤详解

#### 第 1 步：编写观察点文件

在 `agent/observers/` 目录下创建你的 `.py` 文件，必须满足以下规范：

```python
"""
my_observer — 你的观察点描述
"""
import logging
from typing import Any, Dict
from ..core.base import BaseObserver, ObserverResult, AlertLevel

logger = logging.getLogger(__name__)


class MyObserver(BaseObserver):
    """你的观察点说明"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        # 从 config 中读取你的自定义参数
        self.my_param = config.get('my_param', 'default_value')
        # 如需用户填写命令：
        self.command = config.get('command', '')

    def check(self, reporter=None) -> ObserverResult:
        """
        执行检查逻辑

        返回 self.create_result(...)，字段说明：
        - has_alert: 是否触发告警（True/False）
        - alert_level: AlertLevel.INFO / WARNING / ERROR / CRITICAL
        - message: 告警摘要文本
        - details: dict，放入结构化数据（供前端解析）
        - sticky: True 表示持续告警，不受冷却限制
        """
        try:
            # --- 你的检查逻辑 ---
            # 例如：执行命令、解析输出、与预期对比
            # ...

            if something_wrong:
                return self.create_result(
                    has_alert=True,
                    alert_level=AlertLevel.WARNING,
                    message="检测到异常：xxx",
                    details={
                        'key1': 'value1',
                        'changes': [...]  # 推荐放结构化变更列表
                    },
                )

            return self.create_result()  # 无告警

        except Exception as e:
            self.logger.error(f"检查失败: {e}")
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=f"观察点执行异常: {e}",
            )

    def cleanup(self):
        """可选：清理资源"""
        pass
```

**要点**：
- 类名建议用 `XxxObserver` 的驼峰命名
- `check()` 方法签名建议带 `reporter=None` 参数以兼容指标记录
- `details` 字典中的数据会原样传到前端，建议放可读的结构化信息

#### 第 2 步：修改 `observers/__init__.py`

打开 `agent/observers/__init__.py`，添加两处：

```python
# 在文件顶部 import 区域，添加一行：
from .my_observer import MyObserver

# 在 __all__ 列表中，添加一项：
__all__ = [
    # ... 已有的条目 ...
    'MyObserver',
]
```

#### 第 3 步：修改 `core/scheduler.py`

打开 `agent/core/scheduler.py`，在 `_get_observer_classes()` 方法中添加两处：

```python
def _get_observer_classes(self) -> Dict[str, type]:
    # 在 import 区域添加：
    from ..observers.my_observer import MyObserver

    return {
        # ... 已有的映射 ...
        'my_observer': MyObserver,     # ← 添加这行
    }
```

**注意**：字典的 **key**（`'my_observer'`）就是 config.json 中的配置名称，必须与配置项名称完全一致。

#### 第 4 步：修改 `config/loader.py`

打开 `agent/config/loader.py`，在 `DEFAULT_CONFIG['observers']` 字典中添加你的默认配置：

```python
DEFAULT_CONFIG = {
    # ...
    'observers': {
        # ... 已有的条目 ...
        'my_observer': {
            'enabled': True,
            'interval': 60,          # 检查间隔（秒）
            'my_param': 'default',   # 你的自定义参数
            # 如果需要用户填命令：
            # 'command': '',
        },
    },
}
```

#### 第 5 步：修改 `config.json`

打开 `agent/config.json`，在 `"observers"` 对象中添加配置：

```json
{
  "observers": {
    "my_observer": {
      "enabled": true,
      "interval": 60,
      "my_param": "your_value",
      "_comment": "你的观察点说明，_comment 字段仅作注释用"
    }
  }
}
```

#### 第 6 步（可选但推荐）：添加前端告警翻译

如果你希望在 Web 界面上以可读中文显示告警，需编辑 `frontend/src/utils/alertTranslator.js`：

```javascript
// 1. 在 OBSERVER_NAMES 对象中添加中文名称：
export const OBSERVER_NAMES = {
  // ... 已有的 ...
  my_observer: '我的观察点',
}

// 2. 编写翻译函数：
function translateMyObserver(alert) {
  const details = alert.details || {}
  let event = '', impact = '', suggestion = ''

  // 根据 details 中的数据生成三段式翻译
  event = '检测到 xxx 变化'
  impact = '可能影响 xxx'
  suggestion = '建议检查 xxx'

  return makeResult({
    event, impact, suggestion,
    original: alert.message || '',
    log_path: details.log_path || '',
  })
}

// 3. 在 TRANSLATORS 对象中注册：
const TRANSLATORS = {
  // ... 已有的 ...
  my_observer: translateMyObserver,
}
```

#### 第 7 步（可选）：添加告警聚合规则

如果你的观察点需要与其他观察点做根因关联（例如多个相关告警合并显示），编辑 `backend/core/alert_aggregator.py` 中的 `CORRELATION_RULES` 列表。

### 12.3 快速检查清单

添加完成后，请逐项确认：

- [ ] 观察点 `.py` 文件放在 `agent/observers/` 目录下
- [ ] 类继承自 `BaseObserver`，实现了 `check()` 方法
- [ ] `observers/__init__.py` 中有 import 和 `__all__` 条目
- [ ] `core/scheduler.py` 的 `_get_observer_classes()` 中有 import 和字典条目
- [ ] `config/loader.py` 的 `DEFAULT_CONFIG` 中有默认配置
- [ ] `config.json` 中有配置条目且 `enabled: true`
- [ ] （可选）`alertTranslator.js` 中有中文名和翻译函数
- [ ] 重启 Agent 服务后，日志中能看到 `注册: my_observer (间隔 xxxs)`

### 12.4 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 启动报 `未知观察点: xxx` | scheduler.py 中缺少映射 | 检查第 3 步 |
| 启动报 `ImportError` | `__init__.py` 中未导入或文件名拼写错误 | 检查第 2 步和文件名 |
| 观察点不执行 | config.json 中 `enabled: false` 或缺少配置 | 检查第 5 步 |
| Web 端告警显示为原始英文 | 未添加翻译 | 完成第 6 步 |
| 告警不上报到 Web 端 | `check()` 返回的 `has_alert` 未设为 True | 检查 check() 逻辑 |

---

## 十三、开发者教程：修改监测命令/回显/预期结果/Web 显示

本章面向需要**修改已有观察点**行为的开发者。无论你是想改变监测命令、调整回显解析、变更预期结果判断逻辑，还是调整 Web 端的显示方式，都可以参考下面的文件清单和数据流说明。

### 13.1 完整数据流

一条告警从"阵列上执行命令"到"Web 界面展示"经过的完整路径：

```
┌─────────────────── 阵列端（Agent） ───────────────────┐
│                                                        │
│  ① Observer.check()          ← 执行命令、解析回显       │
│       ↓                                                │
│  ② BaseObserver.create_result()  ← 构建 ObserverResult │
│       ↓                                                │
│  ③ Reporter.report()         ← 写入 alerts.log (JSON)  │
│                                                        │
└─────────────────────────┬──────────────────────────────┘
                          │  SSH tail alerts.log
┌─────────────────── Web 后端 ────────────────────────────┐
│                          ↓                              │
│  ④ refresh_array()       ← 解析 JSON 行、存入 DB        │
│       ↓                                                │
│  ⑤ _derive_active_issues_from_db()  ← 推导活跃问题     │
│       ↓                                                │
│  ⑥ API 返回给前端                                       │
│                                                        │
└─────────────────────────┬──────────────────────────────┘
                          │  HTTP / WebSocket
┌─────────────────── Web 前端 ────────────────────────────┐
│                          ↓                              │
│  ⑦ alertTranslator.js   ← 翻译为中文三段式             │
│       ↓                                                │
│  ⑧ useAlertFolding.js   ← 智能折叠                     │
│       ↓                                                │
│  ⑨ FoldedAlertList.vue  ← 列表渲染                     │
│  ⑩ AlertDetailDrawer.vue ← 详情抽屉渲染                │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### 13.2 修改场景与涉及文件对照表

根据你要修改的内容，对照下表找到需要编辑的文件：

| 你要修改的内容 | 涉及文件 | 数据流阶段 |
|--------------|---------|-----------|
| **监测命令**（如改用另一个 CLI 命令） | `agent/observers/{观察点}.py` | ① |
| **回显解析**（如命令输出格式变了） | `agent/observers/{观察点}.py` | ① |
| **预期结果**（如阈值、告警条件） | `agent/observers/{观察点}.py` | ① |
| **告警级别**（如 WARNING → ERROR） | `agent/observers/{观察点}.py` | ① |
| **告警详情结构**（details 字典字段） | `agent/observers/{观察点}.py` | ① |
| **默认配置值**（间隔、阈值等） | `agent/config/loader.py` + `config.json` | ① |
| **恢复告警逻辑** | `agent/observers/{观察点}.py` | ① |
| **活跃问题判断逻辑** | `backend/api/arrays.py` — `_derive_active_issues_from_db()` | ⑤ |
| **活跃问题显示文案** | `backend/api/arrays.py` — `_derive_active_issues_from_db()` | ⑤ |
| **Web 告警翻译**（中文事件/影响/建议） | `frontend/src/utils/alertTranslator.js` | ⑦ |
| **折叠分组逻辑** | `frontend/src/composables/useAlertFolding.js` | ⑧ |
| **告警列表样式/按钮** | `frontend/src/components/FoldedAlertList.vue` | ⑨ |
| **告警详情抽屉** | `frontend/src/components/AlertDetailDrawer.vue` | ⑩ |
| **仪表盘健康状态逻辑** | `frontend/src/views/Dashboard.vue` | ⑩ |
| **阵列详情页布局** | `frontend/src/views/ArrayDetail.vue` | ⑩ |

### 13.3 场景一：修改监测命令

**需求示例**：`card_info` 观察点原来用 `show card all`，现在需要换成 `show board info -all`。

**需要修改的文件**：**1 个**

| 文件 | 修改点 |
|------|--------|
| `agent/config.json` | 修改 `observers.card_info.command` 字段 |

如果新命令**输出格式不变**（仍然是 `No编号 字段名: 值` 的格式），那只需改配置即可。

如果新命令**输出格式变了**，还需修改：

| 文件 | 修改点 |
|------|--------|
| `agent/observers/card_info.py` | 修改 `_parse_cards()` 方法中的解析逻辑 |

**验证方法**：
1. 在阵列上手动执行新命令，确认输出格式
2. 修改 config.json 中的 command 字段
3. 重启 Agent
4. 在 Web 端刷新，观察告警是否正常

### 13.4 场景二：修改回显解析逻辑

**需求示例**：`card_info` 的回显格式从 `No001 BoardId: 03024GRH` 变成了 `Slot[1] BoardId=03024GRH`。

**需要修改的文件**：**1 个**

| 文件 | 修改点 |
|------|--------|
| `agent/observers/card_info.py` | 修改 `_parse_cards()` 方法 |

**修改要点**：
- `_parse_cards()` 中的正则表达式或字符串分割逻辑需要匹配新的格式
- 确保解析后的字段名不变（`BoardId`、`RunningState`、`HealthState`、`Model`），否则需要同步修改 details 结构
- 如果 details 结构变了，需要同步修改前端翻译（见 13.6）

**关键代码位置**：
```python
# agent/observers/card_info.py
def _parse_cards(self, output: str) -> dict:
    """解析命令输出，返回 {卡件编号: {字段: 值}} 的字典"""
    # ← 修改此处的解析逻辑
```

### 13.5 场景三：修改预期结果 / 告警判断条件

**需求示例**：CPU 阈值从 90% 改为 80%；卡件新增 `Mode` 字段需要检查。

#### 改阈值（简单）

**需要修改的文件**：**1 个**

| 文件 | 修改点 |
|------|--------|
| `agent/config.json` | 修改对应观察点的阈值参数 |

示例：CPU 阈值改为 80%：
```json
"cpu_usage": {
  "threshold_percent": 80
}
```

#### 改告警判断逻辑（复杂）

**需要修改的文件**：**1-3 个**

| 文件 | 修改点 | 何时需要 |
|------|--------|---------|
| `agent/observers/{观察点}.py` | `check()` 方法中的判断逻辑 | **必须** |
| `frontend/src/utils/alertTranslator.js` | 翻译函数 | 如果 details 字段名变了 |
| `backend/api/arrays.py` | `_derive_active_issues_from_db()` | 如果影响活跃问题判断 |

**示例**：给 `card_info` 新增 `Mode` 字段检查：

```python
# agent/observers/card_info.py 的 check() 方法中
# 在现有的 RunningState/HealthState 检查后添加：
mode = card_data.get('Mode', '')
if not mode or mode.lower() == 'undefined':
    alerts_list.append({
        'card': card_id,
        'field': 'Mode',
        'value': mode or 'empty',
        'level': 'warning',
        'board_id': card_data.get('BoardId', ''),
    })
```

### 13.6 场景四：修改 Web 端显示

**需求示例**：告警卡片翻译文案不对、想加新的展示字段、想改告警折叠方式。

#### 改告警翻译（中文三段式）

**需要修改的文件**：**1 个**

| 文件 | 修改点 |
|------|--------|
| `frontend/src/utils/alertTranslator.js` | 对应观察点的翻译函数 |

**文件结构**：

```javascript
// 1. OBSERVER_NAMES — 观察点中文名称映射
export const OBSERVER_NAMES = {
  card_info: '卡件信息',
  cpu_usage: 'CPU 监测',
  alarm_type: '告警事件',
  // ...
}

// 2. 各观察点的翻译函数
function translateCardInfo(alert) {
  const details = alert.details || {}
  // 从 details 中提取数据，生成：
  // - event: 发生了什么
  // - impact: 有什么后果
  // - suggestion: 该怎么处理
  // - summary: 小卡片上的简短摘要
  return makeResult({ event, impact, suggestion, summary, ... })
}

// 3. TRANSLATORS — 注册表
const TRANSLATORS = {
  card_info: translateCardInfo,
  cpu_usage: translateCpuUsage,
  alarm_type: translateAlarmType,
  // ...
}
```

**修改要点**：
- 翻译函数的输入是 `alert` 对象，关键数据在 `alert.details` 中
- `alert.details` 的结构由**观察点的 `check()` 方法**决定（见 13.5）
- 如果改了观察点的 details 字段名，必须同步改翻译函数中的字段读取
- `summary` 字段显示在小卡片上，`event/impact/suggestion` 显示在详情抽屉中

#### 改折叠分组逻辑

**需要修改的文件**：**1 个**

| 文件 | 修改点 |
|------|--------|
| `observation_web/frontend/src/composables/useAlertFolding.js` | `getAlertIdentity()` 函数 |

```javascript
// useAlertFolding.js
function getAlertIdentity(alert) {
  const d = alert.details || {}
  switch (alert.observer_name) {
    case 'alarm_type':
      // 按 objType + action 折叠
      return `${d.obj_type || ''}|${d.action || ''}`
    case 'card_info':
      // 按 card + board_id + field 折叠
      return `${d.card || ''}|${d.board_id || ''}|${d.field || ''}`
    // ...
    default:
      // 默认按消息骨架折叠
      return alert.message.replace(/\d+/g, 'N')
  }
}
```

#### 改活跃问题面板显示

**需要修改的文件**：**1-2 个**

| 文件 | 修改点 | 内容 |
|------|--------|------|
| `observation_web/backend/api/arrays.py` | `_derive_active_issues_from_db()` | 活跃问题的标题、消息、类型判断 |
| `observation_web/frontend/src/views/ArrayDetail.vue` | 活跃告警面板模板 | 前端展示样式 |

`_derive_active_issues_from_db()` 中每个观察点的判断逻辑：

```python
# 以 card_info 为例
if observer == 'card_info':
    alerts_info = details.get('alerts', [])
    for a in alerts_info:
        if a.get('level') in ('error', 'warning'):
            issues.append({
                'key': f'card_info_{a.get("card")}_{a.get("field")}',
                'observer': 'card_info',
                'level': a.get('level', 'warning'),
                'title': f'卡件异常: {a.get("card", "?")}',
                'message': f'{a.get("field","?")}: {a.get("value","?")}',
                'alert_id': alert_row.id,
            })
```

#### 改告警详情抽屉

**需要修改的文件**：**1 个**

| 文件 | 修改点 |
|------|--------|
| `observation_web/frontend/src/components/AlertDetailDrawer.vue` | 模板中的条件渲染区域 |

抽屉中的特殊区域（如 alarm_type 的结构化信息）在模板中以 `v-if="isAlarmType"` 等条件控制，可根据需要添加新的观察点专属区域。

### 13.7 修改影响速查表

改动一个地方可能需要连带修改其他地方。以下是**改动传播关系**：

```
观察点 details 字段名变了
    ├─→ alertTranslator.js 翻译函数需同步
    ├─→ useAlertFolding.js 折叠身份需同步（如果用了 details 中的字段）
    ├─→ arrays.py _derive_active_issues_from_db() 需同步（如果涉及活跃问题）
    └─→ AlertDetailDrawer.vue 需同步（如果有观察点专属展示区域）

告警级别变了
    ├─→ alertTranslator.js 中的级别提示文案
    └─→ arrays.py 活跃问题中的 level 判断

config.json 参数名变了
    ├─→ observer.py 中的 config.get() 调用
    └─→ config/loader.py 中的默认值
```

### 13.8 实际案例：alarm_type 观察点的完整修改记录

以下是 `alarm_type` 观察点从初始版本到当前版本的实际修改清单，可作为参考模板：

| 修改内容 | 涉及文件 | 说明 |
|---------|---------|------|
| 目标日志路径改为 `system_alarm.txt` | `observers/alarm_type.py` | `self.log_path` 默认值 |
| 解析 `AlarmType:0/1/2` 格式 | `observers/alarm_type.py` | `_parse_event()` 正则 |
| 提取 `AlarmId:` 和 `objType:` | `observers/alarm_type.py` | `_parse_event()` 解析 |
| Type 0 = INFO，Type 1/2 = WARNING | `observers/alarm_type.py` | `check()` 中 `alert_level` 判断 |
| fault/resume 配对追踪 | `observers/alarm_type.py` | `_active_alarms` 字典 |
| 恢复告警发送 | `observers/alarm_type.py` | `details['recovered'] = True` |
| config.json 中 `log_path` 变更 | `config.json` + `config/loader.py` | 默认配置 |
| 前端翻译函数 | `alertTranslator.js` | `translateAlarmType()` |
| 折叠按 `objType+action` | `useAlertFolding.js` | `getAlertIdentity()` case |
| 活跃问题追踪 fault 未 resume | `arrays.py` | `_derive_active_issues_from_db()` |
| 详情抽屉显示结构化信息 | `AlertDetailDrawer.vue` | alarm_type 专属条件渲染 |
| boardId 在小卡片显示 | `alertTranslator.js` | `translateCardInfo()` summary |

### 13.9 快速验证流程

无论修改了哪个环节，建议按以下步骤验证：

1. **Agent 端修改后**：
   - 重启 Agent：`kill $(pgrep -f observation_points) && python3 -m observation_points &`
   - 在阵列上检查 `tail -f /var/log/observation-points/alerts.log`，确认 JSON 格式正确
   
2. **Web 后端修改后**：
   - 重启后端：`python -m uvicorn backend.main:app --reload --port 9999`
   - 点击阵列详情 → 刷新，观察活跃问题面板
   - 检查 API 响应：`curl http://localhost:9999/api/alerts/recent?limit=5 | python -m json.tool`

3. **Web 前端修改后**：
   - Vite 热更新会自动生效（开发模式下）
   - 检查告警小卡片的翻译文案
   - 点击小卡片，检查详情抽屉
   - 在告警中心检查折叠是否正确

---

## 14. 升级与部署

### 14.1 当前部署方式（手动上传）

若服务器暂未配置 Git，可采用：本地 clone 代码库 → 压缩 → scp 上传 → 服务器解压。此方式易出错，且数据库变更需手动处理。

### 14.2 推荐升级流程

1. **本地 PC** 运行 `./scripts/pack.sh` 打包，产出 `observation_web_vX.Y.Z_YYYYMMDD.tar.gz`
2. **上传**：`scp observation_web_v*.tar.gz user@server:/path/to/observation_web/`
3. **服务器** 运行：`cd /path/to/observation_web && ./scripts/upgrade.sh observation_web_v*.tar.gz`

升级脚本自动完成：备份 → 停服 → 替换代码（保留 config.json、observation_web.db）→ 安装依赖 → 数据库迁移 → 启动 → 健康检查

### 14.3 数据库迁移机制

- 数据库表 `_schema_version` 记录当前迁移版本号
- 迁移脚本位于 `backend/db/migrations/NNN_description.py`，按版本号有序执行
- 启动时自动执行未运行的迁移，幂等安全
- 升级时无需手动操作数据库

### 14.4 回滚

升级失败时执行：`./scripts/upgrade.sh --rollback`，从最近备份 `backups/backup_YYYYMMDD_HHMMSS/` 恢复

### 14.5 离线环境

服务器无法访问外网时，打包时加 `--with-deps`：`./scripts/pack.sh --with-deps`，将 Python wheel 打入 `vendor/`。服务器安装时使用：`pip install --no-index --find-links=vendor/ -r requirements.txt`

### 14.6 升级注意事项

- `config.json` 和 `observation_web.db` 不会被升级包覆盖
- 新增配置项有默认值兜底
- 数据库列变更通过迁移脚本自动处理
