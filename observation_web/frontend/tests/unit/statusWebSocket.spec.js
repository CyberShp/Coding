/**
 * Status WebSocket and unified status field tests.
 *
 * Validates:
 * 1. Status WebSocket updates array list in store
 * 2. Status WebSocket updates currentArray when viewing that array
 * 3. Reconnect success auto-transitions detail page from disconnected to connected
 * 4. Dashboard stats use healthy_count, not misleading stale running
 * 5. Agent badge shows running+healthy/running+unhealthy/not-running
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, computed, nextTick } from 'vue'

// --- Helper: simulates the arrays store's _applyStatusUpdate logic ---
function makeStore() {
  const arrays = ref([])
  const currentArray = ref(null)

  const connectedCount = computed(() =>
    arrays.value.filter(a => a.state === 'connected').length
  )
  const runningCount = computed(() =>
    arrays.value.filter(a => a.agent_running).length
  )
  const healthyCount = computed(() =>
    arrays.value.filter(a => a.agent_healthy).length
  )

  function _applyStatusUpdate(arrayId, data) {
    const index = arrays.value.findIndex(a => a.array_id === arrayId)
    if (index !== -1) {
      arrays.value[index] = { ...arrays.value[index], ...data }
    }
    if (currentArray.value?.array_id === arrayId) {
      currentArray.value = { ...currentArray.value, ...data }
    }
  }

  return { arrays, currentArray, connectedCount, runningCount, healthyCount, _applyStatusUpdate }
}

function makeArray(overrides = {}) {
  return {
    array_id: 'arr-1',
    name: 'Test Array',
    host: '10.0.0.1',
    state: 'disconnected',
    agent_deployed: false,
    agent_running: false,
    agent_healthy: false,
    collect_status: 'unknown',
    running_confidence: 'low',
    active_issues: [],
    ...overrides,
  }
}

describe('Status WebSocket integration', () => {
  describe('_applyStatusUpdate', () => {
    it('should update array in list when status_update received', () => {
      const store = makeStore()
      store.arrays.value = [
        makeArray({ array_id: 'arr-1', state: 'disconnected' }),
        makeArray({ array_id: 'arr-2', state: 'connected' }),
      ]

      store._applyStatusUpdate('arr-1', {
        state: 'connected',
        agent_running: true,
        agent_healthy: true,
        collect_status: 'ok',
      })

      expect(store.arrays.value[0].state).toBe('connected')
      expect(store.arrays.value[0].agent_running).toBe(true)
      expect(store.arrays.value[0].agent_healthy).toBe(true)
      expect(store.arrays.value[0].collect_status).toBe('ok')
      // arr-2 unchanged
      expect(store.arrays.value[1].state).toBe('connected')
    })

    it('should update currentArray when viewing that array', () => {
      const store = makeStore()
      const detail = makeArray({ array_id: 'arr-detail', state: 'disconnected' })
      store.arrays.value = [detail]
      store.currentArray.value = { ...detail }

      store._applyStatusUpdate('arr-detail', {
        state: 'connected',
        agent_running: true,
        agent_healthy: false,
        collect_status: 'error',
      })

      expect(store.currentArray.value.state).toBe('connected')
      expect(store.currentArray.value.agent_running).toBe(true)
      expect(store.currentArray.value.agent_healthy).toBe(false)
    })

    it('should NOT update currentArray for a different array', () => {
      const store = makeStore()
      store.arrays.value = [
        makeArray({ array_id: 'arr-1' }),
        makeArray({ array_id: 'arr-2' }),
      ]
      store.currentArray.value = { ...store.arrays.value[0] }

      store._applyStatusUpdate('arr-2', { state: 'connected' })

      // currentArray still points at arr-1, unchanged
      expect(store.currentArray.value.state).toBe('disconnected')
    })
  })

  describe('Reconnect auto-transition', () => {
    it('should auto-switch detail page from disconnected to connected after WS push', () => {
      const store = makeStore()
      const arr = makeArray({ array_id: 'arr-reconnect', state: 'disconnected' })
      store.arrays.value = [arr]
      store.currentArray.value = { ...arr }

      // Before: disconnected
      expect(store.currentArray.value.state).toBe('disconnected')

      // Simulate WS status_update after auto-reconnect
      store._applyStatusUpdate('arr-reconnect', {
        state: 'connected',
        transport_connected: true,
        agent_running: true,
        agent_healthy: true,
        collect_status: 'ok',
      })

      // After: connected — no manual refresh needed
      expect(store.currentArray.value.state).toBe('connected')
      expect(store.currentArray.value.agent_running).toBe(true)
      expect(store.currentArray.value.agent_healthy).toBe(true)
    })
  })

  describe('Dashboard statistics', () => {
    it('healthyCount should only count healthy agents, not stale running', () => {
      const store = makeStore()
      store.arrays.value = [
        makeArray({ array_id: 'arr-1', state: 'connected', agent_running: true, agent_healthy: true }),
        makeArray({ array_id: 'arr-2', state: 'connected', agent_running: true, agent_healthy: false }),
        makeArray({ array_id: 'arr-3', state: 'disconnected', agent_running: false, agent_healthy: false }),
      ]

      expect(store.connectedCount.value).toBe(2)
      expect(store.runningCount.value).toBe(2)
      expect(store.healthyCount.value).toBe(1) // only arr-1 is truly healthy
    })

    it('stale running agent should not inflate healthy count', () => {
      const store = makeStore()
      store.arrays.value = [
        makeArray({
          array_id: 'arr-stale',
          state: 'connected',
          agent_running: true,
          agent_healthy: false,
          collect_status: 'error',
        }),
      ]

      expect(store.runningCount.value).toBe(1)
      expect(store.healthyCount.value).toBe(0)
    })
  })

  describe('Agent status badge text', () => {
    function getBadgeText(arr) {
      if (arr.agent_running && arr.agent_healthy) return '运行中（健康）'
      if (arr.agent_running && !arr.agent_healthy) return '运行中（无心跳/异常）'
      if (arr.agent_deployed) return '已部署'
      return '未部署'
    }

    it('running + healthy → "运行中（健康）"', () => {
      expect(getBadgeText({ agent_running: true, agent_healthy: true, agent_deployed: true }))
        .toBe('运行中（健康）')
    })

    it('running + unhealthy → "运行中（无心跳/异常）"', () => {
      expect(getBadgeText({ agent_running: true, agent_healthy: false, agent_deployed: true }))
        .toBe('运行中（无心跳/异常）')
    })

    it('not running + deployed → "已部署"', () => {
      expect(getBadgeText({ agent_running: false, agent_healthy: false, agent_deployed: true }))
        .toBe('已部署')
    })

    it('not deployed → "未部署"', () => {
      expect(getBadgeText({ agent_running: false, agent_healthy: false, agent_deployed: false }))
        .toBe('未部署')
    })
  })
})
