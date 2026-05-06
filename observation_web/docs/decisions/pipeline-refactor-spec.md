---
feature_ids: [F-PIPE]
topics: [status-pipeline, alert-sync, component-split, observer-templates]
doc_kind: implementation-spec
created: 2026-04-22
---

# Pipeline Refactor: 3-Phase Implementation Spec

Owner: 宪宪/Opus-46 (architect) → Sonnet (coder) → GPT-5.4 (reviewer)

---

## Phase 1: Fix Status/Alert Real-time Pipeline

**Goal**: Eliminate stale status, missed alerts, and delayed updates on dashboard.

### P1-1: health_checker broadcasts status changes

**File**: `backend/main.py` — `_health_checker()` (line 99-186)

**Root cause**: The health checker updates `_array_status_cache` in-memory every 30s
but NEVER calls `broadcast_status_update()`. Connected clients only see updates
when they poll (30s silentRefresh), meaning status lag = up to 60s worst case.

**Fix**:
1. Import `broadcast_status_update` from `backend/api/websocket.py`
2. After each array's status is updated in the loop, check if state changed
   from previous value. If changed, call `await broadcast_status_update(array_id, {...})`
3. Track previous state per array to detect changes (avoid broadcasting identical state every cycle)

**Implementation detail**:
```python
# At top of _health_checker, before the while loop:
from .api.websocket import broadcast_status_update

# Inside the per-array loop, after updating status_obj:
# Compare with previous state to detect changes
prev_state = _prev_health_state.get(array_id)
cur_state = {
    "state": status_obj.state.value if hasattr(status_obj.state, 'value') else str(status_obj.state),
    "agent_running": status_obj.agent_running,
    "agent_deployed": status_obj.agent_deployed,
}
if prev_state != cur_state:
    _prev_health_state[array_id] = cur_state
    await broadcast_status_update(array_id, {
        "state": cur_state["state"],
        "agent_running": cur_state["agent_running"],
        "agent_deployed": cur_state["agent_deployed"],
        "event": "health_check",
    })
```

Add `_prev_health_state: dict = {}` as module-level dict near other caches.

**Key constraint**: `broadcast_status_update` already has dedup + 500ms throttle
built in (`websocket.py:172-190`), so we don't need extra dedup logic — just
call it and let the manager filter.

### P1-2: Alert broadcast — all new alerts, not just last 10

**File**: `backend/api/arrays.py` — `sync_array_alerts()` (line 286)

**Root cause**: `created_db_alerts[-10:]` — only broadcasts last 10 per sync cycle.
If 20 new alerts arrive, 10 are silently dropped from WS broadcast (they exist in DB
but clients never get the real-time push).

**Fix**: Change line 286 from:
```python
for db_alert in created_db_alerts[-10:]:
```
to:
```python
for db_alert in created_db_alerts:
```

**Risk**: If a massive batch (e.g. 500 alerts) arrives, this could flood the WS.
Add a safety cap at 50 and log a warning if truncated:
```python
broadcast_batch = created_db_alerts
if len(broadcast_batch) > 50:
    logger.warning("Large alert batch (%d), broadcasting first 50", len(broadcast_batch))
    broadcast_batch = broadcast_batch[:50]
for db_alert in broadcast_batch:
    await broadcast_alert({...})
```

### P1-3: Alert sync interval 60s → 20s + broadcast status after sync

**File**: `backend/core/alert_sync.py`

**Changes**:
1. Line 26: Change `_sync_interval_seconds = 60` → `_sync_interval_seconds = 20`
2. In `_sync_one_array()`, after updating `_array_status_cache[array_id].active_issues`
   (line 48), add a WebSocket broadcast so dashboard gets pushed the updated issue count:

```python
# After line 48 (_array_status_cache[array_id].active_issues = issues):
from ..api.websocket import broadcast_status_update
status_obj = _array_status_cache[array_id]
await broadcast_status_update(array_id, {
    "active_issues": issues,
    "event": "alert_sync",
})
```

3. Fix line 50: `logger.debug` → `logger.warning` (already fixed in tech debt? verify)

### P1-4: Deploy endpoint — broadcast status after deploy completes

**File**: `backend/api/arrays.py` — `deploy_agent()` (line 2490-2538)

The endpoint already returns warnings correctly and the frontend already shows them.
But it doesn't broadcast the status change via WS, so other connected clients
(e.g. dashboard) don't know until their next poll.

**Fix**: After line 2535 (status_obj updates), add:
```python
from .websocket import broadcast_status_update
await broadcast_status_update(array_id, {
    "state": status_obj.state.value if hasattr(status_obj.state, 'value') else str(status_obj.state),
    "agent_deployed": status_obj.agent_deployed,
    "agent_running": status_obj.agent_running,
    "event": "deploy",
})
```

Do the same for `start_agent`, `stop_agent`, `restart_agent` endpoints.

---

## Phase 2: ArrayDetail.vue Component Split + alerts.js Store Split

**Goal**: Break 1978-line god component and 385-line store into maintainable units.

### P2-1: ArrayDetail.vue → 4 child components + slim parent

**Current structure** (1978 lines, 12+ concerns):
- Connection status display (state dot, tags, header info)
- Alert display (3 modes: timeline, folded, causal tree)
- Observer panel (list, config, custom observers)
- Operations panel (deploy, start, stop, restart, refresh)
- Agent config drawer
- AI interpretation
- Snapshot diff
- Log viewer
- Performance monitor

**Target split**:

| Component | Responsibility | Approx lines |
|-----------|---------------|-------------|
| `ArrayDetail.vue` (parent) | Route params, data loading, layout grid, provide/inject shared state | ~200 |
| `components/array/ArrayStatusHeader.vue` | Connection state dot, array name, tags, agent status badges | ~150 |
| `components/array/AlertDisplay.vue` | 3 display modes, alert list/timeline, folded list, causal tree, AI interpretation trigger | ~500 |
| `components/array/ObserverPanel.vue` | Observer list, enable/disable, custom observer CRUD, config editor | ~400 |
| `components/array/OperationsPanel.vue` | Deploy/start/stop/restart buttons, status indicators, log viewer trigger | ~300 |

**Rules**:
- Parent provides shared reactive state via `provide()`: `array`, `arrayId`, `statusObj`, `loading`
- Children use `inject()` to access shared state
- Children emit events for actions that need parent coordination
- No prop drilling deeper than 1 level
- Existing component imports (FoldedAlertList, CausalAlertTree, AlertDetailDrawer, etc.) move to the relevant child

### P2-2: alerts.js → 3 composables + slim store

**Current concerns in alerts.js** (385 lines):
1. WebSocket lifecycle (connect/disconnect/reconnect/message handling)
2. AI auto-translation queue (batch fetching, LRU cache)
3. Critical alert banner (detection, timing, desktop notification)
4. Observer suppression rules
5. Data fetching (fetchAlerts, fetchRecentAlerts, stats)

**Target split**:

| File | Responsibility |
|------|---------------|
| `composables/useAlertWebSocket.js` | WS connect/disconnect/reconnect, message parsing, heartbeat |
| `composables/useAITranslation.js` | AI availability check, batch queue, LRU cache, translate single/batch |
| `composables/useCriticalBanner.js` | Critical alert detection, banner state, desktop notification, sound |
| `stores/alerts.js` (slim) | Core state (alerts, recentAlerts, stats), fetch methods, imports composables |

**Rules**:
- Composables are pure functions returning reactive refs + methods
- Store imports and orchestrates composables
- No circular dependencies between composables
- WebSocket composable exposes `onMessage` hook for store to handle incoming alerts

### P2-3: Visual design input (Gemini)

After component split coding is done, @gemini reviews the visual consistency
of the split components — ensures no layout regression, spacing/alignment intact.

---

## Phase 3: Custom Observer Template System Redesign

**Goal**: Replace limited regex-only CustomMonitorObserver with multi-strategy
extraction engine + AI-assisted template builder.

### P3-1: Multi-strategy extraction engine (agent side)

**File**: New `agent/core/extraction.py`

6 extraction strategies:

| Strategy | Input | Operation | Example |
|----------|-------|-----------|---------|
| `pipe` | raw output | Shell-like pipeline: grep → split → index | `free -m` → grep Mem → split → index 2 |
| `kv` | "key=value" or "key: value" text | Parse key-value pairs, extract by key name | `ethtool -S eth0` → extract `rx_crc_errors` |
| `json` | JSON output | JSONPath extraction | `curl /api/health` → `$.status` |
| `table` | Tabular output | Column-based extraction by header name | `df -T -P` → extract `Use%` column |
| `lines` | Multi-line output | Line-by-line pattern matching + count | `dmesg` → count lines matching "error" |
| `diff` | Any output | Compare with previous value, detect change | `cat /sys/class/net/eth0/carrier` → changed? |

Each strategy returns `ExtractionResult`:
```python
@dataclass
class ExtractionResult:
    success: bool
    value: Any           # extracted value (string, number, dict, list)
    raw_output: str      # original command output
    error: Optional[str] # extraction error message
    metadata: dict       # strategy-specific context (previous value for diff, etc.)
```

### P3-2: Enhanced CustomMonitorObserver v2 (agent side)

**File**: Update `agent/observers/custom_monitor.py`

Changes:
1. Replace match_type/match_expression with `strategy` + `strategy_config`
2. Add consecutive threshold support (like built-in observers)
3. Add diff-based change detection (store previous values)
4. Validate regex/jsonpath at config load time (not runtime crash)
5. Add `test_execute()` method — run once, return extraction result without alerting

Config schema v2:
```json
{
  "name": "monitor_port_link",
  "command": "cat /sys/class/net/eth0/carrier",
  "interval": 5,
  "strategy": "diff",
  "strategy_config": {
    "alert_on": "value_changed"
  },
  "alert_level": "warning",
  "alert_message": "Port eth0 link state changed: {old} -> {new}",
  "consecutive_threshold": 1,
  "cooldown": 60
}
```

Backward compatibility: if config has `match_type`/`match_expression` (v1 format),
auto-convert to v2 strategy equivalent.

### P3-3: AI-assisted template builder (backend)

**File**: New function in `backend/core/ai_service.py`

```python
async def nl_to_observer_template(description: str) -> Optional[dict]:
    """
    Convert natural language description to observer template config.
    
    The prompt includes:
    - Knowledge base of 25 built-in observer patterns
    - 6 extraction strategy definitions with examples
    - Available alert conditions and levels
    - Template JSON schema
    """
```

**Prompt structure**:
- System context: "You are a monitoring template designer for storage array test environments"
- Knowledge base: Condensed table of all built-in observers (command, strategy, alert logic)
- Strategy definitions: The 6 strategies with input/output examples
- Output format: Strict JSON matching the v2 config schema
- Temperature: 0.2 (mostly deterministic, slight creativity for command selection)

**Validation layer** (`_validate_observer_template(config)`):
1. Required fields present (name, command, strategy, alert_level)
2. Strategy is one of the 6 known types
3. Interval within bounds [5, 3600] seconds
4. Alert level in {info, warning, error, critical}
5. Command doesn't contain dangerous operators (rm, mkfs, dd, etc.)
6. If strategy is regex-based, validate the pattern compiles

### P3-4: Template builder API endpoint

**File**: Add to `backend/api/query.py` or new `backend/api/observer_templates.py`

```
POST /api/observer-templates/generate
Body: { "description": "监控端口状态变化" }
Response: { "template": {...}, "explanation": "..." }
```

```
POST /api/observer-templates/test-execute
Body: { "template": {...}, "array_id": "xxx" }
Response: { "success": true, "extraction_result": {...}, "raw_output": "..." }
```

### P3-5: Template builder UI (frontend)

- New section in ObserverPanel (from Phase 2 split)
- Text input for natural language description
- "Generate" button → calls API → shows template preview
- Editable form for adjusting parameters
- "Test Run" button → executes on selected array → shows result
- "Deploy" button → saves template + deploys to agent

---

## Execution Pipeline

```
Phase 1 (@sonnet codes) → @gpt52 reviews → merge
    ↓
Phase 2 (@sonnet codes, @gemini visual review) → @gpt52 reviews → merge
    ↓
Phase 3 (@sonnet codes) → @gpt52 reviews → merge
```

No CVO approval needed between phases (pre-approved).
