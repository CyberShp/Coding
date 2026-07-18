# scripts/

运维与测试辅助脚本。所有脚本均从仓库根目录 `config.json` 读取配置（端口等），
运行前请先 `cd observation_web`。

## 运维脚本

| 脚本 | 用途 |
|------|------|
| `upgrade.sh` | 就地升级：备份 → 拉取/解压 → 装依赖 → Alembic 建表/迁移 → 启动 → 健康检查（含 `--rollback`）。端口读 `config.json`。 |
| `pack.sh` | 打包发布产物。 |

## 种子脚本（测试数据注入）

当前有 5 个 seed 脚本，分布在根目录和 `scripts/`，功能有重叠。**暂不删除**（各有仍在用的侧重点），说明如下：

| 脚本 | 位置 | 侧重点 | 写入方式 |
|------|------|--------|----------|
| `seed_demo.py` | scripts/ | 最轻量：快速让前端"有内容可看"的 demo 数据 | 直接写 SQLite |
| `seed_full.py` | scripts/ | 从零创建 tags / arrays / alerts / card_inventory 全套数据 | 直接写 SQLite（async） |
| `seed_test_data.py` | scripts/ | 写测试数据 + 调用 API 做端到端验证（可指定 `--host`） | SQLite + HTTP API |
| `seed_active_issues.py` | 根目录 | 针对"活跃告警与异常"面板：活跃 vs 已恢复告警 | 直接写 SQLite |
| `seed_ack_test.py` | 根目录 | 针对告警确认（ack）机制：含已确认 / 未确认 / 已恢复态 | 直接写 SQLite |

### 合并方向建议（技术债）

这 5 个脚本共享大量样板（连接 DB、生成阵列/告警、时间戳工具）。建议后续收敛为
**单一 `scripts/seed.py` + 子命令/场景开关**，例如：

```
scripts/seed.py --scenario demo|full|active-issues|ack        # 选择数据集
scripts/seed.py --scenario full --verify --host <url>          # 复用 seed_test_data 的 API 验证
```

统一后：把根目录的 `seed_active_issues.py` / `seed_ack_test.py` 一并迁入 `scripts/`，
消除根目录散落；共用 DB 连接与数据生成 helper，避免各脚本各写一份阵列/告警构造逻辑。
迁移属低优先级，需先确认没有其他脚本/文档直接引用这些文件名。
