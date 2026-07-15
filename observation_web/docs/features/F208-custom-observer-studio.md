---
feature_ids: [F208]
related_features: [F203, F204, F205, F206]
topics: [custom-observer, agent, deployment, visibility]
doc_kind: spec
created: 2026-07-16
---

# F208: Custom Observer Studio

> Status: done | Owner: codex

## Why

自定义观察点目前已有自然语言生成、单阵列试运行和一次性下发能力，但模板修改会覆盖历史，标签分配不会持续生效，部署也没有证明 Agent 实际加载了目标配置。用户看到“成功”时仍可能运行旧版本。

## What

- 用自然语言生成配置，同时保留完整专家编辑能力。
- 在任意已连接阵列上执行一次无副作用试运行，展示原始输出、提取值、条件判断和命令退出码。
- 模板每次修改生成不可变版本快照，可查看历史并选择版本回滚。
- 模板可分配给阵列或标签；标签分配是持续期望状态，新加入标签的阵列可被重新协调。
- 模板可见范围分为个人、团队和全局；可见范围不改变阵列端执行范围。
- 配置原子写入 Agent 实际读取的 `/etc/observation-points/config.json`。
- Agent 启动后写出包含配置版本、配置指纹和已加载观察点的运行回执。
- 每个阵列分别显示待下发、下发中、已加载、降级和失败状态，并保留可操作的失败原因。

## Acceptance Criteria

- [x] AC-1: 创建模板时产生版本 1，修改运行配置时产生新版本且旧快照不变。
- [x] AC-2: 模板名称、执行命令、提取策略、条件、频率、连续次数、冷却和消息可编辑。
- [x] AC-3: 自然语言生成结果可先试运行，再保存和分配；试运行不产生告警。
- [x] AC-4: 阵列和标签分配被持久化，重复操作幂等，取消分配后下一次协调会移除观察点。
- [x] AC-5: 部署使用 Agent 的规范配置路径并采用临时文件、解析校验、原子替换和备份。
- [x] AC-6: 只有运行回执中的配置指纹与期望值一致时，部署结果才为“已加载”。
- [x] AC-7: 每个目标阵列的部署状态和错误原因可通过 API 与管理页面查看，无需刷新整页。
- [x] AC-8: 个人、团队、全局可见范围与执行分配相互独立，并随告警元数据上报。
- [x] AC-9: Agent 配置加载失败或自定义观察点初始化失败会进入运行回执，不伪装成启动成功。
- [x] AC-10: 后端、Agent 和前端关键路径测试通过，桌面与移动视口没有遮挡或溢出。

## Dependencies

- Phase 3 extraction engine and template generation API.
- Array SSH connection pool and AgentDeployer.
- Existing admin identity and array/tag models.

## Risk

- 当前系统没有完整团队成员模型，团队可见范围先使用阵列 `owner_team`/模板 `team_scope` 表达，后续可接组织目录。
- 远端阵列可能没有 systemd；运行回执必须同时兼容 systemd 和 legacy 启动。
- 标签内阵列数量较大时需限制并发部署，避免阻塞 API worker。

## Open Questions

- 是否允许普通测试人员创建仅自己可见的模板，取决于后续统一身份体系；本期保留 owner/visibility 数据语义和 API 返回。
- 命令审批、沙箱等安全策略不在本期范围内。
