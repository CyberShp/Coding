---
feature_ids: [F-BUGFIX]
topics: [bugfix, production, agent-detection, heatmap, timer, os_cli]
doc_kind: implementation-spec
created: 2026-05-07
---

# Production Bug Fix — 4 Issues from Internal Deployment

Owner: Opus-46 (root cause) → Sonnet (coder) → GPT-5.4 (reviewer)

---

## Bug 1: Online Agent Count Always 0

### Root Cause (2 layers)

**Layer A — Frontend counts wrong field**

**File**: `frontend/src/views/Dashboard.vue:173-174`
```javascript
const onlineAgentCount = computed(() =>
  filteredArrays.value.filter(a => a.agent_healthy).length,
)
```

`agent_healthy` requires both `agent_running = True` AND a recent heartbeat within the healthy window (300s). For arrays where the agent is running but hasn't sent a heartbeat recently, `agent_healthy` is False but `agent_running` is True. "在线 Agent 数" should count `agent_running`, not `agent_healthy`.

**Layer B — Health checker never probes newly running agents**

**File**: `backend/main.py:193`
```python
if check_count % 10 == 0 and status_obj.agent_running:
```

This gate means the health checker only verifies agent state for arrays where `agent_running` is ALREADY True. On backend startup (or when a new agent is deployed externally), `agent_running` defaults to False in the cache and NEVER gets probed — the gate blocks all probing.

### Fix

**A. Frontend** (`frontend/src/views/Dashboard.vue:173-174`):
```javascript
const onlineAgentCount = computed(() =>
  filteredArrays.value.filter(a => a.agent_running).length,
)
```

**B. Backend** (`backend/main.py:193`):

Change the gate to probe ALL connected arrays, not just those already known to be running:
```python
if check_count % 10 == 0:
```

Remove the `and status_obj.agent_running` condition. The check costs ~2s per array (SSH exec), but only runs every 10 cycles (~5 min), so the load is acceptable.

Also add: after `deployer.check_running()` returns True for a previously-False array, set `status_obj.agent_running = True` and broadcast:
```python
if check_count % 10 == 0:
    deployer = AgentDeployer(conn, config)
    is_running = await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(None, deployer.check_running),
        timeout=10,
    )
    if is_running and not status_obj.agent_running:
        # Newly detected running agent
        status_obj.agent_running = True
        status_obj.agent_deployed = True
        await broadcast_status_update(array_id, {
            "state": "connected",
            "agent_running": True,
            "agent_deployed": True,
            "event": "health_check",
        })
    elif not is_running and status_obj.agent_running:
        # Agent stopped
        status_obj.agent_running = False
        # ... existing warning + auto-redeploy logic
```

---

## Bug 2: Heatmap Connected Arrays Always Gray + Re-connect Button

### Root Cause

**Heatmap color logic** (`frontend/src/utils/arrayStatus.js:41`):
```javascript
if (arr.state !== 'connected') return 'heatmap-offline'  // gray
```

**Connect button** (`frontend/src/views/ArrayDetail.vue:9`):
```html
<el-button v-if="array && array.state !== 'connected'" ...>连接</el-button>
```

Both check `arr.state !== 'connected'`. The backend serialization is correct (`ConnectionState.CONNECTED` → `"connected"`), but the issue is that the status cache initializes all arrays as `ConnectionState.DISCONNECTED` (default). The `list_array_statuses` endpoint re-derives state from `build_runtime_status()` on each call, which correctly sets state to `"connected"` when SSH transport is up. 

**The real issue**: The Dashboard store fetches data periodically, but the heatmap may render BEFORE the full status derivation completes, or the status data arrives via WebSocket broadcast that doesn't include the `state` field.

Check: does the WebSocket `status_update` message from the health_checker include the `state` field? In `main.py:180-188`:
```python
await broadcast_status_update(array_id, {
    "state": cur_state["state"],
    "agent_running": cur_state["agent_running"],
    ...
})
```

Where `cur_state["state"]` is computed from `status_obj.state.value`. If `status_obj.state` was never updated from the default `DISCONNECTED`, the broadcast sends `"disconnected"` even though the SSH connection is up.

**Root cause confirmed**: The health_checker broadcasts `status_obj.state.value`, but `status_obj.state` is only updated by `list_array_statuses()` (which calls `build_runtime_status`). The health_checker READS the cache but DOESN'T re-derive state from transport info. So the broadcast sends the stale default "disconnected".

### Fix

**Backend** (`backend/main.py` — `_health_checker()`, inside the per-array loop):

Before building `cur_state`, re-derive the transport state:
```python
from .core.runtime_status import get_transport_info
transport = get_transport_info(conn)
if transport["transport_connected"]:
    if status_obj.agent_running and status_obj.agent_healthy:
        status_obj.state = ConnectionState.CONNECTED
    elif status_obj.agent_running:
        status_obj.state = ConnectionState.DEGRADED
    else:
        status_obj.state = ConnectionState.CONNECTED
else:
    status_obj.state = ConnectionState.DISCONNECTED
```

This ensures the health_checker broadcast sends the correct state, not the stale default.

---

## Bug 3: Card Sync Timer Resets on Page Switch

### Root Cause

**File**: `frontend/src/views/CardInventory.vue:182-183, 329-346`

Timer state is in **component-local refs** — destroyed on unmount, recreated fresh on mount:
```javascript
const nextAutoSyncAt = ref(Date.now() + AUTO_SYNC_SECONDS * 1000)  // resets every mount
let autoSyncTimer = null
let secondTicker = null

onMounted(() => {
  autoSyncTimer = setInterval(...)     // starts fresh
  secondTicker = setInterval(...)
})

onUnmounted(() => {
  clearInterval(autoSyncTimer)         // killed on navigate away
  clearInterval(secondTicker)
})
```

User navigates away → timers cleared → navigates back → timer shows 05:00 again.

### Fix

Create a Pinia store to persist timer state across navigation:

**New file**: `frontend/src/stores/cards.js`
```javascript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const AUTO_SYNC_SECONDS = 300

export const useCardStore = defineStore('cards', () => {
  // These survive navigation because the store persists
  const nextAutoSyncAt = ref(Date.now() + AUTO_SYNC_SECONDS * 1000)
  const nowTs = ref(Date.now())
  let _autoSyncTimer = null
  let _secondTicker = null

  const nextAutoSyncText = computed(() => {
    const diff = Math.max(0, Math.floor((nextAutoSyncAt.value - nowTs.value) / 1000))
    const mm = String(Math.floor(diff / 60)).padStart(2, '0')
    const ss = String(diff % 60).padStart(2, '0')
    return `${mm}:${ss}`
  })

  function startTimers(syncFn) {
    if (_autoSyncTimer) return  // already running
    _autoSyncTimer = setInterval(() => {
      syncFn()
      nextAutoSyncAt.value = Date.now() + AUTO_SYNC_SECONDS * 1000
    }, AUTO_SYNC_SECONDS * 1000)
    _secondTicker = setInterval(() => {
      nowTs.value = Date.now()
    }, 1000)
  }

  function stopTimers() {
    if (_autoSyncTimer) { clearInterval(_autoSyncTimer); _autoSyncTimer = null }
    if (_secondTicker) { clearInterval(_secondTicker); _secondTicker = null }
  }

  function resetTimer() {
    nextAutoSyncAt.value = Date.now() + AUTO_SYNC_SECONDS * 1000
  }

  return { nextAutoSyncAt, nowTs, nextAutoSyncText, startTimers, stopTimers, resetTimer }
})
```

**Modify**: `frontend/src/views/CardInventory.vue`
- Import `useCardStore`
- Replace local `nextAutoSyncAt`, `nowTs`, `nextAutoSyncText` with store refs
- `onMounted`: call `cardStore.startTimers(syncCards)`
- `onUnmounted`: call `cardStore.stopTimers()`
- After manual sync: call `cardStore.resetTimer()`
- The store keeps `nextAutoSyncAt` across page switches; `secondTicker` only runs when the page is visible (started/stopped on mount/unmount), but the deadline is preserved

**Key**: The `nextAutoSyncAt` timestamp survives in the store. When the user comes back, the timer picks up from where it left off. If the auto-sync deadline passed while away, the next mount triggers an immediate sync.

---

## Bug 4: os_cli Execution Failure — 4 Layered Problems

### Layer 1: `abnormal_reset` observer not declared in config

**NOT a code bug** — the observer IS declared in the hardcoded `DEFAULT_CONFIG` at `agent/config/loader.py:134-147`. The issue is that `/etc/observation-points/config.json` was never created on the array, so the agent falls back to defaults. But:

**The real config issue**: The DEFAULT_CONFIG has the observer, but the `agent/config.json` file (shipped with the agent) may have a different list. When the agent is deployed via SSH, it gets the agent package, not the DEFAULT_CONFIG.

**Fix**: Ensure the deploy script (`backend/core/agent_deployer.py`) generates or includes a proper `config.json` with all built-in observers listed. This is a deployment workflow fix, not a code logic fix.

### Layer 2: `/etc/observation-points/config.json` never created

**File**: `backend/core/agent_deployer.py`

The deploy process uploads the agent package but doesn't create the config file on the target. The agent then tries to read from `/etc/observation-points/config.json` (default path), fails, and falls back to defaults — which may or may not include `abnormal_reset`.

**Fix**: In `agent_deployer.py`'s `deploy()` method, after uploading the package, generate and upload a config.json to the target path:
```python
# After uploading agent package:
config_data = self._generate_agent_config(array_id)
config_path = "/etc/observation-points/config.json"
self._ensure_dir(os.path.dirname(config_path))
self._upload_content(json.dumps(config_data, indent=2), config_path)
```

### Layer 3: `pipe.read(4096)` blocks on small output

**File**: `agent/observers/abnormal_reset.py:43`
```python
chunk = pipe.read(4096)  # blocks until 4096 bytes or EOF
```

`os_cli` output is < 100 bytes. `pipe.read(4096)` waits for the buffer to fill to 4096, which never happens. The reader thread blocks indefinitely. The main thread's 10s timeout kills the process, but the "succeed" keyword is never read because the reader never returned.

**Fix**: Use non-blocking reads:
```python
def _reader_thread(pipe, buf: list, stop_event: threading.Event):
    try:
        while not stop_event.is_set():
            chunk = pipe.read1(4096)  # read1: return immediately with available data
            if not chunk:
                break
            buf.append(chunk)
    except Exception:
        pass
```

`read1(n)` reads UP TO n bytes but returns immediately with whatever is available — doesn't block waiting for the full buffer. If `read1` isn't available on the pipe type, use:
```python
import select
while not stop_event.is_set():
    if select.select([pipe], [], [], 0.5)[0]:  # 0.5s poll
        chunk = pipe.read(4096)
        if not chunk:
            break
        buf.append(chunk)
```

### Layer 4: os_cli is single-command, not interactive shell

**File**: `agent/observers/abnormal_reset.py`

The observer's architecture assumes an interactive 2-phase shell session:
1. Launch `os_cli` as a subprocess
2. Wait for "ready" prompt
3. Send inner command (`cat log_reset.txt`)
4. Read output

But `os_cli` is a **single-command tool**: it executes, writes output to `/OSM/log/cur_debug/log_reset.txt`, and exits. It's NOT an interactive shell that accepts further commands.

**Fix**: Rewrite the observer to match os_cli's actual behavior:
```python
async def check(self):
    # Step 1: Run os_cli (single command, writes to file)
    exit_code, stdout, stderr = self._execute(
        f"{self.os_cli_cmd} {self.inner_cmd}"
    )
    if exit_code != 0:
        return self._no_alert()

    # Step 2: Read the output file directly
    exit_code, content, _ = self._execute(
        f"cat /OSM/log/cur_debug/log_reset.txt"
    )
    if exit_code != 0:
        return self._no_alert()

    # Step 3: Parse for abnormal reset keywords
    for keyword in ABNORMAL_KEYWORDS:
        if keyword in content.lower():
            return self._alert(
                level="warning",
                message=f"Abnormal reset detected: {keyword}",
            )
    return self._no_alert()
```

This eliminates the subprocess pipe entirely — uses the standard `_execute()` method (SSH exec_command) which has proper timeouts and doesn't block.

---

## Execution Order

```
Bug 1 + Bug 2 (tightly coupled — both involve health_checker + status cache)
  → Bug 3 (independent, frontend only)
  → Bug 4 (independent, agent side)
  → pytest
  → @gpt52 review
  → merge
```

---

## Constraints

- Bug 1+2 are backend changes in `main.py` + frontend change in `Dashboard.vue` — test with real SSH connections if possible
- Bug 3 is purely frontend — verify timer persists across route changes
- Bug 4 changes agent-side code — must be tested with real os_cli on a storage array (or mocked)
- Do NOT change the `build_runtime_status()` logic — it's correct; the issue is the health_checker not feeding it current data
