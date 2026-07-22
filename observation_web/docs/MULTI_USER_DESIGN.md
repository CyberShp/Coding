# 多用户模型与自定义监测统一 — 设计契约

> 2026-07-20 与产品负责人问答确认。平台尚在测试阶段未部署，无存量迁移包袱。
> 本文档是实现的唯一契约；实现偏离本文档须先改文档。

## 一、事实前提（问答确认）

| 维度 | 结论 |
|---|---|
| 团队结构 | 按特性小组（网络/交换/前端/后端/管理…），组内有细分 |
| 小组实体 | **复用阵列 L1 标签当小组，入组自选**（可多组、可改） |
| IP 稳定性 | 一人一机，但重启/VPN 重连即变 → **IP 不可作身份** |
| 账户体系 | **轻量账户：昵称+口令**，登录一次长期有效 |
| 登录强制度 | **渐进：匿名只读，任何写操作需登录** |
| 权限哲学 | **人人可操作，但署名+可追溯**（不设审批卡点） |
| admin | **账户加 is_admin 标志，可多管理员**；config.json 原账户保留为应急后门 |
| 存量数据 | 测试阶段未部署 → 标 legacy/公共，任何登录用户可管，零迁移风险 |

## 二、隔离与共享的界线（总纲）

界线不在"功能"，在**影响范围**：

1. **客观事实**（阵列/告警/指标/卡件）＝ 全局共享，登录才能改。
2. **改变世界的动作**（部署监测、ack、定时任务、改阈值、删数据）＝ 全局生效 + **署名到个人** + 可追溯 + 特定撤销保护。
3. **个人视角**（偏好/关注/视图/草稿）＝ 用户私有（键=user_id，不再是 IP）。
4. **自定义能力**＝ 生命周期：创建（默认**小组可见**）→ 可**升全局**（创建者即可，署名）→ 他人**引用+版本固定**复用 → 部署后全局生效带来源标识。

## 三、多用户碰撞规则（逐条）

| 场景 | 规则 |
|---|---|
| 自定义监测可见性 | 默认创建者所在小组（L1 标签）可见；创建者可发布到全局库；可选保留私有草稿态 |
| 复用语义 | **引用 + 版本固定**：部署绑定 definition 的某个版本；作者改动出新版本，不自动影响已部署；部署方可选择升级 |
| 同阵列同名/同指标 | **共存**；agent 侧实例名自动带 `@owner` 后缀防覆盖；告警 details 带 `source_definition_id/version/deployed_by` |
| ack | **全局生效**（一人确认全员可见"已确认"），署名到账户；**撤销仅限确认者本人或 admin** |
| 内置观察点配置 | 全局一份降级为**默认值**；新增按 L1 标签/按阵列覆盖层，小组各管各的 |
| 测试期告警 | 阵列被测试任务锁定期间，该阵列新告警自动 `is_expected=1` + 关联 task_id（复用 alerts 现有字段），默认视图折叠；解锁恢复 |
| 生命周期 | 不自动回收；**健康度仪表盘**展示每个部署的最后告警时间/创建者/版本/使用情况，人工清理 |
| force_unlock | 修复无鉴权现状：仅锁持有者或 admin |
| 破坏性全局动作（删阵列/清系统告警/归档运行） | 需登录+署名；删阵列需 admin |

## 四、四件套统一

统一为 **MonitorDefinition（监测定义）** 单一模型：

```
monitor_definitions
  id, name, description
  owner_id → users        # 创建者
  team_tag_id → tags(L1)  # 归属小组
  visibility: draft | team | global
  exec_location: agent | backend   # 下发 agent 执行 / 后端 SSH 执行
  current_version
monitor_definition_versions   # 不可变快照
  definition_id, version, spec_json(命令/规则/阈值/间隔/告警级别), created_by, created_at
monitor_deployments           # 部署=引用某版本
  definition_id, version, array_id, deployed_by, status(active/paused/removed),
  desired_hash, loaded_hash, last_alert_at   # 健康度
```

- **query_templates 的 auto_monitor** → exec_location=backend 的 MonitorDefinition（交互式"立即执行"保留在 query 页，仅"定时监测固化"迁走）。
- **monitor_templates + Assignment/Deployment（codex）** → 吸收为本模型的 agent 路径；沿用其 hash 校验/加载回执机制。
- **scheduled_tasks** → 模板型任务迁入 backend 路径；纯 cron 跑命令不产告警的保留原样（非监测）。
- **observer_configs（内置观察点）不合并**——它是内置观察点的配置覆盖，另建 `observer_config_overrides(observer_name, scope_type: global|tag|array, scope_id, params)`。

## 五、账户体系（Phase 1 详设）

```
users: id, nickname(unique), password_hash(sha256+salt), is_admin, created_at, last_login_at
user_teams: user_id, tag_id(L1)   # 入组自选，可多组
```
- 登录 `POST /auth/user-login` 签发用户 token（复用现 HMAC 机制，sub=user_id）。
- 中间件解析 token → `request.state.user`；无 token 匿名（只读）。
- **写操作门禁**：统一依赖 `require_user`；GET 全部开放。
- 现 admin token 兼容保留（应急后门）；`require_admin` 改为 `user.is_admin or legacy_admin_token`。
- 首个 admin：首个注册用户自动 is_admin，或 legacy admin 登录后授予。
- 前端：登录/注册对话框（写操作 401 时弹出）、顶栏当前用户、入组选择。
- 署名：ack/部署/模板/任务等所有写路径记录 user_id + nickname（替代 acked_by_ip 等）。

## 六、实施阶段

- **Phase 1 账户与门禁**：users/user_teams 表+迁移、注册登录 API、require_user 门禁接入全部写端点、is_admin、force_unlock 修权、前端登录框+当前用户、偏好迁移到 user_id 键。
- **Phase 2 统一监测**：MonitorDefinition 三表+迁移、四件套 API 收敛（旧端点兼容期共存）、版本固定部署、同阵列共存后缀、告警来源标识、健康度仪表盘页、全局库/小组库前端。
- **Phase 3 碰撞细则**：ack 撤销保护、测试期 expected 自动标记、observer_config 按标签/阵列覆盖、删阵列 admin 化、清理系统告警署名。

每阶段独立可交付、附测试、跑全套回归后合入 main。
