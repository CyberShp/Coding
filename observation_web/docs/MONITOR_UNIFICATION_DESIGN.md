# 自定义监测统一 — 实施契约（供 opus 动工）

> 2026-07-20 起草（fable，仅方案不动代码）。前置：多用户 Phase 1-3 已合入 main 且通过交叉评审（commit 2b72570）。平台测试阶段、无真实部署 → 迁移无存量包袱。
> 本文档是实施唯一契约；实现偏离须先改文档。

## 0. 先纠正"四件套"的说法

调研把 query_templates / monitor_templates / scheduled_tasks / observer_configs 并称"四件套"，但它们**语义分三类，不该强行合成一张表**：

| 现有模型 | 真实语义 | 归属 |
|---|---|---|
| `monitor_templates`(+version/assignment/deployment) | 持久监测定义，agent 执行，会产告警 | **统一基座** |
| `query_templates.auto_monitor=True` 部分 | 持久监测定义，backend SSH 执行，会产告警 | **并入统一** |
| `scheduled_tasks`(query_template_id 型) | 定时执行+套规则告警 | **并入统一**（作 backend 定时） |
| `query_templates` 交互式部分（commands+rule，立即执行） | ad-hoc 一次性查询，**不产持久告警** | **保留**（改名 QueryPreset，去掉 monitor 字段） |
| `scheduled_tasks`(纯 command 型，无规则不产告警) | 运维定时任务（跑命令存输出） | **保留**（明确它是 ops-task 不是 monitor） |
| `observer_configs` + `observer_config_overrides` | 内置观察点的配置覆盖层 | **不并入**（配置≠定义，Phase 3 已做覆盖层） |

**统一的准确定义**：把"持久的、会产告警的自定义监测定义"归一到单一模型，执行位置用字段区分（agent / backend）。其余各归其位。

## 1. 统一基座 = 扩展 monitor_templates（不新建表）

理由：monitor_templates 已在 Phase 2 多用户化（owner_user_id/visibility/team_scope/version/version 快照/assignment/deployment/健康度），是最成熟的载体。新建 MonitorDefinition 会重复这些且要迁数据，得不偿失。

**新增字段**（迁移，down_revision = 当前 head，实施时 grep 确认）：
- `exec_location` String(16) default `"agent"`，取值 `agent` | `backend`。
  - `agent`：现状，下发 custom_monitors 给 agent 执行（monitor_deployments/assignment 那套）。
  - `backend`：后端调度器定时 SSH 执行命令 + 套规则产告警（复用已存在的 scheduler `_execute_auto_monitor`/`_alert_from_rule`）。
- `commands_json` Text nullable：backend 定义可多命令（agent 定义仍用单 `command`；两者取一，见 §2）。

**backend 定义的调度**：exec_location=backend 且 is_enabled 的定义，由 `core/scheduler` 注册为 interval job（间隔=interval 字段），job 内对 `monitor_arrays`（新增字段或复用 assignment 的 target）执行命令、套规则、命中则 create_alert（observer_name=`custom:{name}@{owner}`，与 agent 侧来源标识一致）。这套逻辑 Phase 2 前我已在 scheduler 写过（add_auto_monitor/_execute_auto_monitor/_alert_from_rule），迁移即复用。

## 2. 规则与命令的 canonical 表达（关键映射）

两套字段不同，统一以 monitor_templates 的表达为准，query 侧映射进来：

| canonical (monitor_templates) | query_templates 来源 | 说明 |
|---|---|---|
| `match_type`(regex/…) | `rule_type` | valid_match/invalid_match → regex；regex_extract → extract |
| `match_expression` | `pattern` | 正则本体 |
| `match_condition`(found/not_found) | `rule_type`+`expect_match` | valid_match&expect=found；invalid_match→not_found |
| `alert_level` | 固定 warning（query 无此字段） | 迁移时默认 warning，可后续编辑 |
| `alert_on_mismatch`(query) | → 语义并入 match_condition | 不单独保留 |
| 多命令 | query `commands`(JSON array) | **命令数不匹配**：agent 定义历来单 `command`；backend 定义允许多命令 → 用新增 `commands_json`。统一模型：`command`(单，agent 用) 与 `commands_json`(多，backend 用) 二选一，按 exec_location 决定读哪个。迁移 query→backend 定义时写 commands_json。 |
| `monitor_arrays` | query `monitor_arrays`(JSON array_ids) | backend 定义的目标阵列；agent 定义用 assignment/deployment 表达目标 |

写一个 `core/monitor_rule.py`：`canonical_rule_from_query(query_template)` 与 `evaluate(output, rule)`（后者复用现有 QueryEngine._apply_rule，避免重写规则引擎）。

## 3. 数据迁移（一次性脚本 + 迁移内）

测试阶段无存量，脚本主要保证代码路径通 + 可空跑：
1. `query_templates` 中 `auto_monitor=True` 的行 → 建 monitor_templates 行：exec_location=backend，规则按 §2 映射，commands_json=其 commands，monitor_arrays 保留，owner_user_id/visibility 缺失则默认（team/无 owner，或归 legacy）。原 query 行的 auto_monitor 相关字段置废弃（保留列但不再消费，或迁移后清 auto_monitor=False）。
2. `scheduled_tasks` 中有 `query_template_id` 且该模板会套规则的 → 建 exec_location=backend 定义（cron→interval 近似，或保留 cron 表达另加字段）；纯 command 型保留在 scheduled_tasks（标注为 ops-task）。
3. 迁移写成幂等脚本 `scripts/migrate_to_unified_monitors.py`（可重复跑不重复建，用 name+owner 判重），非 alembic DDL（DDL 只加 exec_location/commands_json 列）。

## 4. 执行路径统一后

- **agent 定义**：不变，走 monitor_deployments 的 assignment→deploy→custom_monitors 下发。
- **backend 定义**：scheduler 加载所有 exec_location=backend & enabled 的定义为 interval job；CRUD 时动态增删 job（复用 add_auto_monitor/remove）。job 执行套规则产告警。
- **query 页**："立即执行"保留（ad-hoc）；原"定时监测固化"开关改为"创建为 backend 监测定义"，跳到统一监测页或直接建定义。
- **健康度仪表盘**：现只覆盖 agent 部署；扩展为同时展示 backend 定义的运行状态（最后执行/最后告警/下次运行）。

## 5. 前端统一

- 统一"自定义监测"页（现 AdminMonitors）展示所有定义，标 `exec_location` 徽标（agent/后端）。
- 创建时选执行位置：agent（部署到阵列）/ backend（后端定时跑）。
- CustomQuery 页：保留查询构建器 + 立即执行；"定时监测"入口改为"另存为监测定义"。
- 可见性/owner/发布/复用 UI 已在 Phase 2 就绪，统一后自动适用。

## 6. 分阶段实施（建议 opus 按此拆）

- **U1 模型与迁移**：加 exec_location/commands_json 列 + 迁移；canonical rule helper + 单测。
- **U2 backend 执行路径**：scheduler 加载/调度 backend 定义、套规则产告警、CRUD 动态增删 job；健康度扩展 backend 状态。
- **U3 数据搬运**：query auto_monitor + scheduled 模板型 → backend 定义的幂等迁移脚本；query 页"定时监测"改道；scheduled_tasks 纯命令型标注 ops-task。
- **U4 前端统一**：监测页 exec_location 徽标+创建选执行位置；CustomQuery 改道；健康度页含 backend。
- 每阶段独立可交付、附测试、全套回归后合入。

## 7. 验收标准
- 后端/前端全套测试绿（当前基线 后端 664 / 前端 198）+ 每阶段新增测试。
- 一个 backend 监测定义能：创建→被 scheduler 定时执行→异常时产带来源标识的告警→在健康度看到状态。
- 一个 agent 监测定义行为与统一前一致（回归）。
- query 页"立即执行"不受影响；"定时监测"正确改道创建 backend 定义。
- 可见性/owner/发布/复用规则对两种 exec_location 一致生效。

## 8. 风险与兼容
- **命令单/多不匹配**是最大坑（§2）——按 exec_location 分读 command/commands_json，勿混。
- backend 定义的 SSH 执行会加后端负载（与之前"事件驱动降 SSH"方向权衡）——interval 下限保护（如 ≥60s）、复用 ssh_pool 并发限流。
- cron→interval 的近似：scheduled_tasks 用 cron，backend 定义用 interval；若需保留 cron 语义，backend 定义也加可选 cron_expr（二选一触发器）。
- 兼容期：旧 query auto_monitor / scheduled 端点在迁移后保留只读或 410，前端改道后再下线。
- observer_configs 明确不动（避免把配置层卷进来）。
