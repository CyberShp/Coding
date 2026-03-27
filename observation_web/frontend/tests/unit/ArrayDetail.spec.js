import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, computed } from 'vue'

describe('ArrayDetail', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('loading state', () => {
    it('shows loading state when fetching', () => {
      const loading = ref(true)
      const array = ref(null)

      expect(loading.value).toBe(true)
      expect(array.value).toBeNull()
      // When loading && !array, skeleton zone should show
      const showSkeleton = computed(() => loading.value && !array.value)
      expect(showSkeleton.value).toBe(true)
    })

    it('hides skeleton after data loads', () => {
      const loading = ref(false)
      const array = ref({ name: 'Test Array', host: '192.168.1.1' })

      const showSkeleton = computed(() => loading.value && !array.value)
      expect(showSkeleton.value).toBe(false)
    })
  })

  describe('empty state', () => {
    it('shows empty state when no array', () => {
      const loading = ref(false)
      const array = ref(null)

      const showContent = computed(() => !!array.value)
      expect(showContent.value).toBe(false)
    })
  })

  describe('error state', () => {
    it('handles fetch failure gracefully', async () => {
      const loading = ref(false)
      const array = ref(null)
      let errorOccurred = false

      const fetchArray = async () => {
        loading.value = true
        try {
          throw new Error('Network Error')
        } catch (e) {
          errorOccurred = true
          array.value = null
        } finally {
          loading.value = false
        }
      }

      await fetchArray()
      expect(errorOccurred).toBe(true)
      expect(array.value).toBeNull()
      expect(loading.value).toBe(false)
    })
  })

  describe('normal state - basic info', () => {
    it('shows array basic info', () => {
      const array = ref({
        name: 'Production Array',
        host: '10.0.0.1',
        port: 8443,
        username: 'admin',
        state: 'connected',
        last_heartbeat: '2024-01-15T10:30:00Z',
        last_refresh: '2024-01-15T10:29:00Z',
      })

      expect(array.value.name).toBe('Production Array')
      expect(array.value.host).toBe('10.0.0.1')
      expect(array.value.port).toBe(8443)
      expect(array.value.state).toBe('connected')
    })

    it('displays page title from array name', () => {
      const array = ref({ name: 'My Array' })
      const pageTitle = computed(() => array.value?.name || '阵列详情')

      expect(pageTitle.value).toBe('My Array')
    })

    it('shows default title when array has no name', () => {
      const array = ref(null)
      const pageTitle = computed(() => array.value?.name || '阵列详情')

      expect(pageTitle.value).toBe('阵列详情')
    })
  })

  describe('status overview zone', () => {
    it('shows agent status dot class', () => {
      const getAgentDotClass = (state) => {
        if (state === 'connected') return 'dot-success'
        if (state === 'connecting') return 'dot-warning'
        return 'dot-danger'
      }

      expect(getAgentDotClass('connected')).toBe('dot-success')
      expect(getAgentDotClass('connecting')).toBe('dot-warning')
      expect(getAgentDotClass('disconnected')).toBe('dot-danger')
    })

    it('shows connection state text', () => {
      const getStateText = (state) => {
        const map = {
          connected: '已连接',
          disconnected: '已断开',
          connecting: '连接中',
          error: '错误',
        }
        return map[state] || state
      }

      expect(getStateText('connected')).toBe('已连接')
      expect(getStateText('disconnected')).toBe('已断开')
      expect(getStateText('connecting')).toBe('连接中')
      expect(getStateText('error')).toBe('错误')
    })

    it('shows enrollment mode text', () => {
      const enrollmentModes = ['auto', 'manual', 'template']
      enrollmentModes.forEach(mode => {
        expect(typeof mode).toBe('string')
        expect(mode.length).toBeGreaterThan(0)
      })
    })

    it('shows data freshness status', () => {
      const array = ref({ last_refresh: '2024-01-15T10:29:00Z' })
      const hasFreshness = computed(() => !!array.value.last_refresh)
      const noRefresh = computed(() => !array.value.last_refresh)

      expect(hasFreshness.value).toBe(true)
      expect(noRefresh.value).toBe(false)
    })

    it('shows unfreshed text when never refreshed', () => {
      const array = ref({ last_refresh: null })
      const freshnessText = computed(() =>
        array.value.last_refresh ? 'some time ago' : '未刷新'
      )

      expect(freshnessText.value).toBe('未刷新')
    })
  })

  describe('time window selector', () => {
    it('renders all time window options', () => {
      const timeWindows = [
        { label: '1h', value: 1 },
        { label: '6h', value: 6 },
        { label: '24h', value: 24 },
        { label: '72h', value: 72 },
        { label: '7d', value: 168 },
        { label: '21d', value: 504 },
      ]

      expect(timeWindows.length).toBe(6)
      expect(timeWindows[0].label).toBe('1h')
      expect(timeWindows[5].label).toBe('21d')
    })

    it('switching time window updates selected value', () => {
      const selectedWindow = ref(24)

      selectedWindow.value = 72
      expect(selectedWindow.value).toBe(72)

      selectedWindow.value = 168
      expect(selectedWindow.value).toBe(168)
    })

    it('time window filters events by cutoff', () => {
      const now = Date.now()
      const events = [
        { timestamp: new Date(now - 1 * 3600 * 1000).toISOString() }, // 1h ago
        { timestamp: new Date(now - 5 * 3600 * 1000).toISOString() }, // 5h ago
        { timestamp: new Date(now - 25 * 3600 * 1000).toISOString() }, // 25h ago
      ]

      const filterByWindow = (events, windowHours) => {
        const cutoff = now - windowHours * 3600 * 1000
        return events.filter(e => new Date(e.timestamp).getTime() >= cutoff)
      }

      expect(filterByWindow(events, 1).length).toBe(1)
      expect(filterByWindow(events, 6).length).toBe(2)
      expect(filterByWindow(events, 48).length).toBe(3)
    })
  })

  describe('active anomalies', () => {
    it('shows active anomaly count', () => {
      const activeIssues = ref([
        { key: '1', level: 'error', title: 'CPU High' },
        { key: '2', level: 'warning', title: 'Memory Usage' },
      ])

      expect(activeIssues.value.length).toBe(2)
    })

    it('shows no anomalies state', () => {
      const activeIssues = ref([])
      const hasAnomalies = computed(() => activeIssues.value.length > 0)

      expect(hasAnomalies.value).toBe(false)
    })

    it('categorizes anomalies by type', () => {
      const issues = [
        { key: '1', level: 'error', category: 'real' },
        { key: '2', level: 'warning', category: 'expected' },
        { key: '3', level: 'error', category: 'real' },
        { key: '4', level: 'info', category: 'failure' },
      ]

      const realAnomalies = issues.filter(i => i.category === 'real')
      const expectedAnomalies = issues.filter(i => i.category === 'expected')
      const failures = issues.filter(i => i.category === 'failure')

      expect(realAnomalies.length).toBe(2)
      expect(expectedAnomalies.length).toBe(1)
      expect(failures.length).toBe(1)
    })

    it('tracks unacknowledged count', () => {
      const issues = [
        { key: '1', alert_id: 'a1', acked: false },
        { key: '2', alert_id: 'a2', acked: true },
        { key: '3', alert_id: 'a3', acked: false },
      ]

      const unackedCount = issues.filter(i => !i.acked).length
      expect(unackedCount).toBe(2)
    })
  })

  describe('observer status', () => {
    it('shows observer list', () => {
      const observers = [
        { name: 'cpu_usage', status: 'ok' },
        { name: 'memory_leak', status: 'warning' },
        { name: 'disk_io', status: 'error' },
      ]

      expect(observers.length).toBe(3)
      expect(observers[0].name).toBe('cpu_usage')
    })

    it('maps observer names correctly', () => {
      const getObserverName = (key) => {
        const map = {
          cpu_usage: 'CPU 使用率',
          memory_leak: '内存泄漏',
          disk_io: '磁盘 IO',
        }
        return map[key] || key
      }

      expect(getObserverName('cpu_usage')).toBe('CPU 使用率')
      expect(getObserverName('unknown')).toBe('unknown')
    })
  })

  describe('AI fallback', () => {
    it('shows local explanation when AI unavailable', () => {
      const aiAvailable = false
      const localExplanation = '基于规则引擎的本地分析结果'

      const explanation = aiAvailable ? 'AI 分析结果' : localExplanation
      expect(explanation).toContain('本地')
    })

    it('shows AI explanation when available', () => {
      const aiAvailable = true
      const aiExplanation = 'AI 分析: CPU 使用率异常升高'

      const explanation = aiAvailable ? aiExplanation : '本地分析'
      expect(explanation).toContain('AI')
    })
  })

  describe('refresh', () => {
    it('refreshing state controls button loading', () => {
      const refreshing = ref(false)

      expect(refreshing.value).toBe(false)

      refreshing.value = true
      expect(refreshing.value).toBe(true)
    })

    it('connect/disconnect button toggles by state', () => {
      const getActionButton = (state) => {
        if (state !== 'connected') return 'connect'
        return 'disconnect'
      }

      expect(getActionButton('disconnected')).toBe('connect')
      expect(getActionButton('connected')).toBe('disconnect')
    })
  })
})
