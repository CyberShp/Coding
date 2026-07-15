# Agent 可靠性与运维说明

## 本轮优化

| 问题 | 当前处理 |
| --- | --- |
| 普通日志污染 `alerts.log` | 运行日志改写 `agent.log`，结构化告警文件只保留 JSONL |
| 后端不可达导致 Agent 无法启动 | 移除启动前无限 ping，断网时继续本地采集 |
| 慢观察点阻塞所有观察点 | 使用有界线程池并发调度，每个观察点最多一个在途任务 |
| 采集失败显示为正常 | `collection_ok` 区分正常静默与采集故障，周期上报观察点健康状态 |
| HTTP 推送丢失或线程暴涨 | SQLite outbox 持久化、批量发送、指数退避、队列上限和优雅排空 |
| Agent 重启丢失基线 | 原子状态文件保存计数器、游标、趋势窗口和活跃告警 |
| 日志轮转漏读、`dmesg` 重复告警 | 使用 inode+offset 游标；`dmesg` 事件指纹持久化 |
| 多阵列时间不一致 | Agent 事件使用带时区 UTC；后端统一转换到数据库本地时间约定 |
| 文件与 push 指标重复 | 指标携带 `sample_id`，后端合并时去重并按真实时间排序 |
| 更新失败后无法恢复 | 更新前编译和导入检查，替换失败回滚，备份保留到新进程初始化成功 |
| 配置写入后未生效 | systemd 支持 `SIGHUP` reload；部署写配置后强制重载并检查结果 |

## 本地持久文件

- `/var/log/observation-points/alerts.log`：纯 JSONL 告警。
- `/var/log/observation-points/agent.log`：Agent 运行日志，20 MB x 3 轮转。
- `/var/log/observation-points/metrics.jsonl`：指标数据，10 MB 单备份轮转。
- `/var/log/observation-points/traffic.jsonl`：端口流量明细，按保留时间原子清理。
- `/var/lib/observation-points/outbox.sqlite3`：尚未确认送达的 push 数据。
- `/var/lib/observation-points/state.json`：观察点运行基线和增量游标。
- `/var/lib/observation-points/cooldown.json`：告警冷却状态。

不要在 Agent 运行时手动删除后三个状态文件。必须清空时应先停止服务，否则会造成重复告警或观察盲区。

## 关键配置

```json
{
  "global": {
    "max_workers": 4,
    "subprocess_timeout": 10,
    "max_memory_mb": 50,
    "health_report_interval_seconds": 30,
    "state_path": "/var/lib/observation-points/state.json"
  },
  "reporter": {
    "push_timeout": 5,
    "push_queue_max": 10000,
    "push_batch_size": 100,
    "outbox_path": "/var/lib/observation-points/outbox.sqlite3",
    "cooldown_path": "/var/lib/observation-points/cooldown.json"
  }
}
```

`card_info` 默认启用并使用 `anytest intfboardallinfo`。`controller_state`、`disk_state` 暂时默认禁用；确认设备命令后再启用，避免产生无效采集状态。

## 运维检查

```bash
systemctl status observation-points
systemctl reload observation-points
tail -f /var/log/observation-points/agent.log
sqlite3 /var/lib/observation-points/outbox.sqlite3 'select kind,count(*) from outbox group by kind;'
```

升级后应确认 `agent.log` 出现调度器启动信息，`alerts.log` 每行均可独立解析为 JSON，并观察 outbox 的 pending 数量能在后端恢复后下降到零。
