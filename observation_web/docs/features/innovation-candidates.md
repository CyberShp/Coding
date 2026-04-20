---
feature_ids: [F200, F201, F202, F203, F204, F205, F206, F207]
topics: [innovation, roadmap, test-environment]
doc_kind: feature-candidates
created: 2026-04-21
updated: 2026-04-21
---

# Innovation Feature Candidates

> Context: This is a **test environment** monitoring platform. ~30 users, each watching their
> own target arrays. Alerts are expected test outcomes. Core value = completeness, timeliness,
> precision of alert capture for test engineers.

---

## Tier 1: Test Workflow Enhancement (测试丝滑体验)

### F203: Collection Heartbeat Indicator (采集心跳指示器)

**Problem**: Test engineer can't tell if "no alerts" means "nothing happened" or "collection broke".

**Solution**: Per-array heartbeat badge in ArrayDetail status strip:
- `● Active (last collect 3s ago)` → green
- `● Delayed (last collect 45s ago, normal=10s)` → yellow
- `● Interrupted (last collect 3m ago)` → red

**Effort**: 2 days. Backend already tracks last_collect_ts. Frontend adds badge.

---

### F204: Observer Activity Map (Observer 活跃地图)

**Problem**: Can't tell which observers are actively collecting vs silently dead.

**Solution**: Dot indicator row above alert area in ArrayDetail:
`[alarm_type ●] [disk_smart ●] [rebuild ○] [bbu ●] [fan_temp ○]`
- Green ● = produced data in last hour
- Gray ○ = no data in 1+ hour
- Red ● blinking = currently producing alerts

**Effort**: 2 days. Backend has observer_status. Frontend adds indicator strip.

---

### F205: Live Alert Stream Mode (告警实时流)

**Problem**: Alerts show as static list. Engineer must refresh or wait for WS push + re-sort.

**Solution**: Toggle to "stream mode" in ArrayDetail alerts zone:
- New alerts scroll in from bottom like `tail -f`
- Auto-scroll to latest; pause with Shift or Pause button
- Paused state shows "N new alerts waiting" badge
- Action ↔ alert causality becomes intuitive (do something → see result in <3s)

**Effort**: 4 days. WebSocket exists. Add virtual-scroll stream view component.

---

### F206: Alert Arrival Latency Badge (告警到达延迟标签)

**Problem**: "Is 30s delay the array being slow, or our collection being slow?"

**Solution**: Per-alert latency badge:
- `⚡ 2.8s` (green, <5s, hidden by default)
- `⏱ 12s` (gray, 5-15s)
- `⚠ 45s` (orange, >15s, hover shows breakdown: array reaction / collection gap / transit / processing)

**Effort**: 3 days. Agent payload has timestamp. Diff against array log original timestamp.

---

### F207: Smart Fold with Progress Detection (智能折叠 + 进度检测)

**Problem**: Same fault triggers 47 repeated alerts (every 10s poll). Noise buries signal.
But "Rebuilding 12%" → "Rebuilding 58%" is NOT repetition — it's progress.

**Solution**: Enhanced FoldedAlertList:
- Fully identical messages: fold with count `× 47, first 14:02 | last 14:09`
- Messages with changing numbers (rebuild %, sector count): show as progress timeline
- Never fold messages where the delta carries meaning

**Effort**: 1 week. Modify FoldedAlertList fold logic + add progress pattern detection.

---

## Tier 2: Intelligence Layer (智能化)

### F200: Causal Inference Engine (因果推理引擎)

**Problem**: 10 alerts fire simultaneously. Which is root cause, which is consequence?

**Solution**: Temporal co-occurrence mining on alert streams. Auto-build causal DAG:
`disk_smart warning → alarm_type(disk offline) → alarm_type(degraded) → alarm_type(rebuild)`

Frontend: alert tree instead of flat list. Handle root node = handle everything.

**Base**: alert_store timestamps + observer_name + array_id + AI interpret-alert.
**Effort**: 1-2 weeks. Core algorithm ~200 lines.

---

### F201: Natural Language Query (自然语言查询)

**Problem**: Finding specific historical patterns requires manual navigation across pages.

**Solution**: Single input box. Intent recognition → SQL generation → execute → chart/text result.
Examples: "最近三天哪些阵列 rebuild 过？" / "arr_001 上周的 disk_smart 告警有多少？"

**Base**: AI endpoint exists, SQLite schema is clear, structured intent → no hallucination.
**Effort**: 2-3 weeks. 80% value from 20% query templates.

---

### F202: Adaptive Baseline (自适应基线 / 告警免疫系统)

**Problem**: Fixed thresholds don't account for per-array differences. Old disk at 200
reallocated sectors is normal; new disk at 1 is alarming.

**Solution**: Per-array rolling 30-day median baseline. Alert when `value > baseline + 3σ`.
- Old arrays stop false-alarming on known-high values
- New arrays catch tiny anomalies early
- Expected noise reduction: 60-80%

**Effort**: 1 week. APScheduler job + per-array stats table.

---

## Priority Matrix

| # | Feature | Solves | Effort | Impact |
|---|---------|--------|--------|--------|
| 1 | F203 Heartbeat | "Is it collecting?" anxiety | 2d | Immediate trust |
| 2 | F204 Observer Map | Silent observer death | 2d | Completeness visibility |
| 3 | F205 Live Stream | Action↔alert causality | 4d | Flow state for testing |
| 4 | F206 Latency Badge | "Why slow?" attribution | 3d | Precision diagnostics |
| 5 | F207 Smart Fold | Signal buried in noise | 1w | Information density |
| 6 | F200 Causal DAG | Root cause identification | 2w | Intelligence leap |
| 7 | F201 NL Query | Cross-page navigation pain | 3w | Workflow revolution |
| 8 | F202 Adaptive Baseline | False alarm fatigue | 1w | Noise reduction |
