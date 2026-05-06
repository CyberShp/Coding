---
feature_ids: [F-REVIEW]
topics: [refactor, tests, architecture, quality]
doc_kind: implementation-spec
created: 2026-04-22
---

# Critical Review Refactor — Implementation Spec

Owner: 宪宪/Opus-46 (architect) → Sonnet (coder) → GPT-5.4 (reviewer)
Excluded: saved_password encryption (CVO decision)

---

## Work Item 1: Fix 11 Failing Tests (P0)

### Root Cause Analysis

**Group A — Missing tables in test fixtures (4 tests)**

| Test | Error | Root Cause |
|------|-------|------------|
| `test_alert_api_contract::test_get_alerts_empty` | `no such table: baseline_stats` | Fixture creates alerts table but not baseline_stats |
| `test_alert_store::test_create_alerts_batch` | FK error: `arrays.tag_id → tags` | Fixture creates arrays table without creating tags table first |
| `test_alert_store::test_create_alerts_batch_empty` | Same FK error | Same |
| `test_advanced::test_bulk_alert_insert_performance` | Likely same FK error | Same |

**Fix**: In each test fixture that creates tables, use `Base.metadata.create_all(engine)` 
to create ALL tables (respects FK order), rather than cherry-picking individual tables.
If the fixture intentionally creates only specific tables, add the missing dependencies
(`tags` table before `arrays`, `baseline_stats` alongside alerts).

**Group B — Card inventory endpoint changed (3 tests)**

| Test | Error | Root Cause |
|------|-------|------------|
| `test_features_v2::test_create_card` | `405 Method Not Allowed` | POST endpoint was removed or route changed |
| `test_features_v2::test_search_multi_keyword_and` | Same | Same |
| `test_features_v2::test_crud_card` | Same | Same |

**Fix**: Check `backend/api/card_inventory.py` for current endpoints. Either:
- The POST endpoint was removed → delete the tests (they test dead code)
- The route prefix changed → update test URLs to match current router prefix
- The HTTP method changed → update test to use correct method

**Group C — Recovery tracking logic changed (2 tests)**

| Test | Error | Root Cause |
|------|-------|------------|
| `test_v2_changes::test_card_info_recovery_records_timestamp` | `len(active_issues) == 0`, expected 1 | `_derive_active_issues` logic changed |
| `test_v2_changes::test_card_info_relapse_pops_recovery` | Same pattern | Same |

**Fix**: Read the current `_derive_active_issues_from_db()` or the in-memory active issues
logic. Update test expectations to match current behavior, OR fix the logic if it's a genuine regression.

**Group D — Missing temp file in test (2 tests)**

| Test | Error | Root Cause |
|------|-------|------------|
| `test_v2_changes::test_deploy_uses_staging_path` | `FileNotFoundError: /tmp/test.tar.gz` | Test doesn't create the fixture file before calling deploy |
| `test_v2_changes::test_deploy_upload_staging_fails` | Same | Same |

**Fix**: Add fixture setup that creates `/tmp/test.tar.gz` (or use `tmp_path` fixture),
and teardown that cleans it up. Or mock `open()` / `_upload_package()`.

---

## Work Item 2: `arrays.py` Split (P1)

**Current**: `backend/api/arrays.py` — 3105 lines, god module

**Target split**:

| New Module | Responsibility | Estimated Lines |
|-----------|---------------|----------------|
| `backend/api/arrays.py` | Array CRUD (list, get, create, delete, status) + router aggregation | ~800 |
| `backend/api/array_agent_ops.py` | Agent deploy/start/stop/restart endpoints | ~500 |
| `backend/api/array_alert_sync.py` | `sync_array_alerts()`, alert parsing, sync position tracking | ~600 |
| `backend/api/array_status.py` | `_array_status_cache`, `ArrayStatus` class, `_get_array_status()`, `_derive_active_issues_from_db()`, presence/watchers | ~400 |

**Rules**:
1. `array_status.py` owns `_array_status_cache` and `ArrayStatus` — other modules import from it
2. `arrays.py` remains the router aggregation point (includes sub-routers or re-exports endpoints)
3. All existing imports from other modules (`from ..api.arrays import _array_status_cache`) must still work
   — either keep re-exports in `arrays.py` or update import sites
4. `sync_array_alerts` moves to `array_alert_sync.py` but is still imported by `alert_sync.py` (core)
5. No behavioral changes — pure structural refactor, all endpoints keep same URL paths

**Import dependency order**: `array_status.py` → `array_alert_sync.py` → `array_agent_ops.py` → `arrays.py`

**Critical**: `_array_status_cache` is imported by at least:
- `backend/main.py` (health_checker)
- `backend/core/alert_sync.py` (_sync_one_array)
- `backend/core/runtime_status.py`
- `backend/api/websocket.py` (if any)

Update all import sites or add re-export in `arrays.py`:
```python
# arrays.py — backward compat re-exports
from .array_status import _array_status_cache, ArrayStatus, _get_array_status
```

---

## Work Item 3: Background Task Exception Visibility (P1)

**Current**: `backend/main.py` — 3 background loops catch all exceptions with `logger.warning`

**Fix**: Add consecutive failure tracking and system alert escalation.

```python
# Near top of main.py, add:
_bg_task_failures: dict = {}  # task_name → consecutive_failure_count

def _track_bg_failure(task_name: str, error: Exception, threshold: int = 3):
    """Track consecutive failures; escalate to system alert after threshold."""
    count = _bg_task_failures.get(task_name, 0) + 1
    _bg_task_failures[task_name] = count
    logger.warning(f"{task_name} failed (#{count}): {error}")
    if count >= threshold:
        sys_warning(
            task_name,
            f"{task_name} has failed {count} consecutive times: {error}",
            {"consecutive_failures": count, "last_error": str(error)},
        )

def _reset_bg_failure(task_name: str):
    """Reset failure counter on successful execution."""
    _bg_task_failures.pop(task_name, None)
```

**Apply to all 3 loops**:

1. `_idle_connection_cleaner()` — wrap inner try with `_track_bg_failure("idle_cleaner", e)`,
   add `_reset_bg_failure("idle_cleaner")` after successful cycle
2. `_health_checker()` — same pattern with `"health_checker"`
3. Per-array errors in health_checker — track per `f"health_check_{array_id}"`

Don't change `_auto_reconnect_saved_arrays` (runs once, not a loop).

---

## Work Item 4: Dashboard.vue Split (P2)

**Current**: `frontend/src/views/Dashboard.vue` — 1134 lines

**Target split**:

| Component | Responsibility | Approx Lines |
|-----------|---------------|-------------|
| `Dashboard.vue` (parent) | Layout, data loading, provide context | ~200 |
| `components/dashboard/SummaryCards.vue` | 4 summary stat cards (total, online, alerting, offline) | ~120 |
| `components/dashboard/ArrayHeatmap.vue` | Heatmap grid with status dots + click-to-navigate | ~200 |
| `components/dashboard/TrendCharts.vue` | Alert trend line chart + health pie chart | ~200 |
| `components/dashboard/DashboardAlerts.vue` | Recent alerts stream + filtering | ~200 |

**Rules**:
1. Parent provides shared state via `provide('dashboard', {...})`
2. Extract duplicated status functions (`getStatusDotClass`, `getHeatmapDotClass`, `getArrayStatusClass`)
   into shared utility: `frontend/src/utils/arrayStatus.js`
3. Extract chart config objects into utility files (not inline computed)
4. Extract hardcoded colors into CSS custom properties in Dashboard parent:
   ```css
   :root {
     --color-healthy: #52c41a;
     --color-warning: #faad14;
     --color-error: #ff4d4f;
     --color-offline: #8c8c8c;
   }
   ```
   Children reference `var(--color-healthy)` etc.

**Gemini scope**: After split, @gemini reviews visual consistency — no layout regression,
spacing/alignment intact, color tokens properly applied.

---

## Work Item 5: 401 Interceptor (P2)

**File**: `frontend/src/api/index.js`

**Current**: No response interceptor for 401. Expired tokens cause silent failures.

**Fix**: Add response interceptor:

```javascript
http.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      // Only auto-logout if we thought we were logged in
      if (authStore.token) {
        authStore.logout()
        // Show notification
        ElMessage.warning('登录已过期，请重新登录')
        // Navigate to login
        const router = (await import('../router')).default
        router.push('/admin/login')
      }
    }
    return Promise.reject(error)
  }
)
```

**Warning**: The Pinia store and router may not be available at module init time.
Use lazy import pattern (dynamic `import()`) to avoid circular dependency.

Also apply to `httpLong` instance.

---

## Work Item 6: Observer Health Tracking + Auto-Backoff (P2)

**File**: `agent/core/scheduler.py`

**Current**: Observer crash → `logger.error` → retry next cycle (no backoff, no health tracking)

**Fix**: Add per-observer health tracking in scheduler:

```python
# In Scheduler.__init__:
self._observer_failures: dict = {}  # observer_name → consecutive_count
self._observer_backoff: dict = {}   # observer_name → next_allowed_time

# In the main loop, before calling observer.check():
def _should_run_observer(self, name: str) -> bool:
    backoff_until = self._observer_backoff.get(name, 0)
    return time.time() >= backoff_until

# After observer.check() fails:
def _record_observer_failure(self, name: str):
    count = self._observer_failures.get(name, 0) + 1
    self._observer_failures[name] = count
    # Exponential backoff: 1min, 2min, 4min, 8min, max 15min
    backoff_seconds = min(60 * (2 ** (count - 1)), 900)
    self._observer_backoff[name] = time.time() + backoff_seconds
    logger.warning(
        f"[{name}] 连续失败 {count} 次，退避 {backoff_seconds}s"
    )
    # After 10 consecutive failures, report to backend
    if count >= 10 and count % 10 == 0:
        self.reporter.report(ObserverResult(
            observer_name=name,
            has_alert=True,
            level="error",
            message=f"Observer {name} has crashed {count} consecutive times",
            sticky=True,
        ))

# After successful check():
def _record_observer_success(self, name: str):
    if name in self._observer_failures:
        prev_count = self._observer_failures.pop(name, 0)
        self._observer_backoff.pop(name, None)
        if prev_count >= 3:
            logger.info(f"[{name}] 恢复正常（此前连续失败 {prev_count} 次）")
```

---

## Work Item 7: alertTranslator Data-ification (P3)

**Current**: `frontend/src/utils/alertTranslator.js` — 625 lines of switch/map logic

**Target**:
1. Extract all translation mappings into `frontend/src/utils/alertTranslations.json`
2. Reduce `alertTranslator.js` to a thin lookup layer (~50 lines)

**Structure of JSON**:
```json
{
  "observers": {
    "cpu_usage": { "name": "CPU 使用率", "description": "CPU 持续高负载" },
    "memory_leak": { "name": "内存泄漏", "description": "内存持续递增" },
    ...
  },
  "levels": {
    "critical": "严重",
    "error": "错误",
    "warning": "警告",
    "info": "信息"
  },
  "keywords": {
    "threshold exceeded": "超过阈值",
    "recovery": "恢复正常",
    ...
  }
}
```

**Simplified translator**:
```javascript
import translations from './alertTranslations.json'

export function translateObserver(name) {
  return translations.observers[name]?.name || name
}

export function translateLevel(level) {
  return translations.levels[level] || level
}

export function translateMessage(msg) {
  let result = msg
  for (const [en, zh] of Object.entries(translations.keywords)) {
    result = result.replace(new RegExp(en, 'gi'), zh)
  }
  return result
}

// Keep isCriticalAlert as-is (it's logic, not translation)
```

**Rule**: `isCriticalAlert()` and any behavioral logic stays in the JS file.
Only pure translation data moves to JSON.

---

## Execution Pipeline

All items execute sequentially by Sonnet, gpt52 reviews the batch:

```
Sonnet: W1 (tests) → W2 (arrays.py split) → W3 (bg task visibility)
      → W4 (Dashboard split) → W5 (401 interceptor) → W6 (observer health)
      → W7 (alertTranslator)
      → @gpt52 review entire batch
      → Fix any findings
      → Merge
```

Gemini reviews visual consistency after W4 (Dashboard split) is coded.

No CVO approval needed between items (pre-approved).
