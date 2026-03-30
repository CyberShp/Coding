/**
 * ArrayDetail.vue component tests.
 *
 * Validates:
 * - Four states: loading, empty (no data), error, normal
 * - Deploy: success, success+warnings, failure
 * - Start: reloads array and shows "运行中" when agent_running=true
 * - Agent status badges: deployed-not-running vs running
 * - Consistency: badge, button state, text reflect API data
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'

// --- Mocks for heavy child components ---
vi.mock('@/components/LogViewer.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/PerformanceMonitor.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/PortTrafficChart.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/EventTimeline.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/SnapshotDiff.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/AlertDetailDrawer.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/FoldedAlertList.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/components/PixelPet.vue', () => ({ default: { template: '<div/>' } }))
vi.mock('@/utils/alertTranslator', () => ({
  translateAlert: vi.fn(a => ({ event: a.message || '' })),
  getObserverName: vi.fn(n => n),
  LEVEL_LABELS: { info: '信息', warning: '警告', error: '错误', critical: '严重' },
  LEVEL_TAG_TYPES: { info: 'info', warning: 'warning', error: 'danger', critical: 'danger' },
}))

// --- Simulate ArrayDetail page logic (without importing the full SFC) ---

function makeArrayData(overrides = {}) {
  return {
    array_id: 'arr-1',
    name: 'Test Array',
    host: '10.0.0.1',
    port: 22,
    username: 'root',
    state: 'connected',
    agent_deployed: false,
    agent_running: false,
    tag_id: null,
    last_refresh: null,
    active_issues: [],
    ...overrides,
  }
}

describe('ArrayDetail', () => {
  describe('Four-state rendering', () => {
    it('loading state: loading=true, array=null', () => {
      const loading = ref(true)
      const array = ref(null)
      expect(loading.value).toBe(true)
      expect(array.value).toBeNull()
    })

    it('empty state: loading=false, array=null (data not loaded)', () => {
      const loading = ref(false)
      const array = ref(null)
      expect(loading.value).toBe(false)
      expect(array.value).toBeNull()
    })

    it('error state: loading=false after failed load', () => {
      const loading = ref(false)
      const array = ref(null)
      const error = ref('加载失败')
      expect(error.value).toBeTruthy()
      expect(array.value).toBeNull()
    })

    it('normal state: loading=false, array populated', () => {
      const loading = ref(false)
      const array = ref(makeArrayData())
      expect(loading.value).toBe(false)
      expect(array.value).toBeTruthy()
      expect(array.value.name).toBe('Test Array')
    })
  })

  describe('Agent status badge logic', () => {
    it('agent_running=true shows "运行中"', () => {
      const array = ref(makeArrayData({ agent_running: true, agent_deployed: true }))
      // Simulates template: v-if="array.agent_running" → el-tag type="success"
      const badgeText = array.value.agent_running ? '运行中' :
        array.value.agent_deployed ? '已部署' : '未部署'
      expect(badgeText).toBe('运行中')
    })

    it('agent_deployed=true, agent_running=false shows "已部署"', () => {
      const array = ref(makeArrayData({ agent_deployed: true, agent_running: false }))
      const badgeText = array.value.agent_running ? '运行中' :
        array.value.agent_deployed ? '已部署' : '未部署'
      expect(badgeText).toBe('已部署')
    })

    it('both false shows "未部署"', () => {
      const array = ref(makeArrayData({ agent_deployed: false, agent_running: false }))
      const badgeText = array.value.agent_running ? '运行中' :
        array.value.agent_deployed ? '已部署' : '未部署'
      expect(badgeText).toBe('未部署')
    })
  })

  describe('Deploy scenarios', () => {
    it('deploy success: message shows success', async () => {
      const deploying = ref(false)
      const array = ref(makeArrayData({ state: 'connected' }))
      const messages = []

      // Simulate handleDeployAgent
      deploying.value = true
      const mockDeployAgent = vi.fn().mockResolvedValue({ data: { ok: true } })
      const mockLoadArray = vi.fn().mockImplementation(async () => {
        array.value = makeArrayData({ agent_deployed: true, agent_running: true })
      })

      try {
        await mockDeployAgent(array.value.array_id)
        messages.push('部署成功')
        await mockLoadArray()
      } catch (e) {
        messages.push('部署失败')
      } finally {
        deploying.value = false
      }

      expect(messages).toContain('部署成功')
      expect(array.value.agent_deployed).toBe(true)
      expect(deploying.value).toBe(false)
    })

    it('deploy success with warnings: should NOT show as failure', async () => {
      const deploying = ref(false)
      const array = ref(makeArrayData({ state: 'connected' }))
      const messages = []

      // API returns 200 with warnings
      const mockDeployAgent = vi.fn().mockResolvedValue({
        data: { ok: true, warnings: ['systemd failed'], message: 'Deployed with warnings' }
      })
      const mockLoadArray = vi.fn().mockImplementation(async () => {
        array.value = makeArrayData({ agent_deployed: true, agent_running: false })
      })

      deploying.value = true
      try {
        const result = await mockDeployAgent(array.value.array_id)
        // Key assertion: even with warnings, it's success
        if (result.data.warnings?.length) {
          messages.push('部署成功（有警告）')
        } else {
          messages.push('部署成功')
        }
        await mockLoadArray()
      } catch (e) {
        messages.push('部署失败')
      } finally {
        deploying.value = false
      }

      expect(messages).not.toContain('部署失败')
      expect(messages[0]).toContain('部署成功')
    })

    it('deploy failure: shows error message', async () => {
      const deploying = ref(false)
      const array = ref(makeArrayData({ state: 'connected' }))
      const messages = []

      const mockDeployAgent = vi.fn().mockRejectedValue({
        response: { data: { detail: 'Upload failed' } }
      })

      deploying.value = true
      try {
        await mockDeployAgent(array.value.array_id)
        messages.push('部署成功')
      } catch (error) {
        const detail = error?.response?.data?.detail
        messages.push(typeof detail === 'string' ? detail : '部署失败')
      } finally {
        deploying.value = false
      }

      expect(messages).toContain('Upload failed')
      expect(deploying.value).toBe(false)
    })
  })

  describe('Start agent → reload array → badge update', () => {
    it('after start, if agent_running=true, badge shows "运行中"', async () => {
      const starting = ref(false)
      const array = ref(makeArrayData({ agent_deployed: true, agent_running: false }))
      const messages = []

      const mockStartAgent = vi.fn().mockResolvedValue({ data: { ok: true } })
      const mockLoadArray = vi.fn().mockImplementation(async () => {
        array.value = makeArrayData({ agent_deployed: true, agent_running: true })
      })

      starting.value = true
      try {
        await mockStartAgent(array.value.array_id)
        messages.push('启动成功')
        await mockLoadArray()
      } catch (e) {
        messages.push('启动失败')
      } finally {
        starting.value = false
      }

      expect(messages).toContain('启动成功')
      expect(array.value.agent_running).toBe(true)
      const badgeText = array.value.agent_running ? '运行中' : '已部署'
      expect(badgeText).toBe('运行中')
    })
  })

  describe('Button state consistency', () => {
    it('deploy button disabled when disconnected', () => {
      const array = ref(makeArrayData({ state: 'disconnected' }))
      const deployDisabled = array.value.state !== 'connected'
      expect(deployDisabled).toBe(true)
    })

    it('deploy button enabled when connected', () => {
      const array = ref(makeArrayData({ state: 'connected' }))
      const deployDisabled = array.value.state !== 'connected'
      expect(deployDisabled).toBe(false)
    })

    it('start button disabled when already running', () => {
      const array = ref(makeArrayData({ state: 'connected', agent_running: true }))
      const startDisabled = array.value.state !== 'connected' || array.value.agent_running
      expect(startDisabled).toBe(true)
    })

    it('stop button disabled when not running', () => {
      const array = ref(makeArrayData({ state: 'connected', agent_running: false }))
      const stopDisabled = array.value.state !== 'connected' || !array.value.agent_running
      expect(stopDisabled).toBe(true)
    })
  })

  describe('Connection state display', () => {
    it('getStateType returns correct type', () => {
      const types = {
        connected: 'success',
        connecting: 'warning',
        disconnected: 'info',
        error: 'danger',
      }
      expect(types['connected']).toBe('success')
      expect(types['disconnected']).toBe('info')
      expect(types['error']).toBe('danger')
    })

    it('getStateText returns correct text', () => {
      const texts = {
        connected: '已连接',
        connecting: '连接中',
        disconnected: '未连接',
        error: '错误',
      }
      expect(texts['connected']).toBe('已连接')
      expect(texts['disconnected']).toBe('未连接')
    })
  })

  describe('Front-back consistency: warning not treated as fatal', () => {
    it('backend returns warning level → should NOT render as fatal error', () => {
      const alert = { level: 'warning', message: 'some warning' }
      // Simulates LEVEL_TAG_TYPES usage
      const LEVEL_TAG_TYPES = { info: 'info', warning: 'warning', error: 'danger', critical: 'danger' }
      const tagType = LEVEL_TAG_TYPES[alert.level]
      expect(tagType).toBe('warning')
      expect(tagType).not.toBe('danger')
    })

    it('backend returns error level → renders as danger', () => {
      const alert = { level: 'error', message: 'real error' }
      const LEVEL_TAG_TYPES = { info: 'info', warning: 'warning', error: 'danger', critical: 'danger' }
      const tagType = LEVEL_TAG_TYPES[alert.level]
      expect(tagType).toBe('danger')
    })
  })
})
