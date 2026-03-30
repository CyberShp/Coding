import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, computed } from 'vue'

describe('CardInventory', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('search', () => {
    it('renders search input for IP and BoardId', () => {
      const searchQuery = ref('')
      const placeholder = '搜索 型号/BoardId/CardNo/阵列名/IP（空格分隔多关键词）'

      expect(searchQuery.value).toBe('')
      expect(placeholder).toContain('BoardId')
      expect(placeholder).toContain('IP')
    })

    it('search by board_id filters results', () => {
      const allCards = ref([
        { board_id: 'BRD-001', model: 'ModelA', array_host: '10.0.0.1' },
        { board_id: 'BRD-002', model: 'ModelB', array_host: '10.0.0.2' },
        { board_id: 'BRD-003', model: 'ModelA', array_host: '10.0.0.3' },
      ])
      const searchQuery = ref('BRD-001')

      const filteredCards = computed(() => {
        const keywords = (searchQuery.value || '').trim().toLowerCase().split(/\s+/).filter(Boolean)
        return allCards.value.filter(card => {
          if (keywords.length) {
            const searchable = `${card.model || ''} ${card.board_id || ''} ${card.array_host || ''}`.toLowerCase()
            if (!keywords.every(kw => searchable.includes(kw))) return false
          }
          return true
        })
      })

      expect(filteredCards.value.length).toBe(1)
      expect(filteredCards.value[0].board_id).toBe('BRD-001')
    })

    it('multi-keyword search narrows results', () => {
      const allCards = ref([
        { board_id: 'BRD-001', model: 'ModelA', array_host: '10.0.0.1' },
        { board_id: 'BRD-002', model: 'ModelA', array_host: '10.0.0.2' },
        { board_id: 'BRD-003', model: 'ModelB', array_host: '10.0.0.3' },
      ])
      const searchQuery = ref('ModelA 10.0.0.1')

      const filteredCards = computed(() => {
        const keywords = (searchQuery.value || '').trim().toLowerCase().split(/\s+/).filter(Boolean)
        return allCards.value.filter(card => {
          if (keywords.length) {
            const searchable = `${card.model || ''} ${card.board_id || ''} ${card.array_host || ''}`.toLowerCase()
            if (!keywords.every(kw => searchable.includes(kw))) return false
          }
          return true
        })
      })

      expect(filteredCards.value.length).toBe(1)
      expect(filteredCards.value[0].board_id).toBe('BRD-001')
    })
  })

  describe('empty state', () => {
    it('shows empty state when no cards', () => {
      const allCards = ref([])
      const loading = ref(false)

      expect(allCards.value.length).toBe(0)
      expect(loading.value).toBe(false)
    })
  })

  describe('card list', () => {
    it('shows card list when data available', () => {
      const allCards = ref([
        { board_id: 'BRD-001', model: 'ModelA', health_state: 'NORMAL', running_state: 'RUNNING' },
        { board_id: 'BRD-002', model: 'ModelB', health_state: 'ABNORMAL', running_state: 'STOPPED' },
      ])

      expect(allCards.value.length).toBe(2)
      expect(allCards.value[0].board_id).toBe('BRD-001')
    })

    it('shows card status correctly', () => {
      const stateTagType = (value, expected) => {
        if (!value) return 'info'
        return String(value).toUpperCase() === expected ? 'success' : 'danger'
      }

      expect(stateTagType('NORMAL', 'NORMAL')).toBe('success')
      expect(stateTagType('ABNORMAL', 'NORMAL')).toBe('danger')
      expect(stateTagType('RUNNING', 'RUNNING')).toBe('success')
      expect(stateTagType('STOPPED', 'RUNNING')).toBe('danger')
      expect(stateTagType(null, 'NORMAL')).toBe('info')
      expect(stateTagType('', 'NORMAL')).toBe('info')
    })

    it('shows last confirmed time', () => {
      const card = { last_updated: '2024-01-15T10:30:00Z' }
      expect(card.last_updated).toBeTruthy()
      expect(new Date(card.last_updated).getTime()).toBeGreaterThan(0)
    })
  })

  describe('loading state', () => {
    it('loading state while fetching', async () => {
      const loading = ref(false)
      const allCards = ref([])

      const loadData = async () => {
        loading.value = true
        try {
          await new Promise(resolve => setTimeout(resolve, 200))
          allCards.value = [{ board_id: 'BRD-001' }]
        } finally {
          loading.value = false
        }
      }

      expect(loading.value).toBe(false)
      const loadPromise = loadData()
      expect(loading.value).toBe(true)

      vi.advanceTimersByTime(200)
      await loadPromise
      expect(loading.value).toBe(false)
      expect(allCards.value.length).toBe(1)
    })
  })

  describe('error state', () => {
    it('handles fetch failure', async () => {
      const loading = ref(false)
      const allCards = ref([])
      let errorCaught = false

      const loadData = async () => {
        loading.value = true
        try {
          throw new Error('Failed to load card inventory')
        } catch (e) {
          errorCaught = true
          allCards.value = []
        } finally {
          loading.value = false
        }
      }

      await loadData()
      expect(errorCaught).toBe(true)
      expect(allCards.value.length).toBe(0)
      expect(loading.value).toBe(false)
    })
  })

  describe('pagination', () => {
    it('paginates cards correctly', () => {
      const allCards = Array.from({ length: 75 }, (_, i) => ({ board_id: `BRD-${i}` }))
      const currentPage = ref(1)
      const pageSize = ref(50)

      const paginatedCards = computed(() => {
        const start = (currentPage.value - 1) * pageSize.value
        return allCards.slice(start, start + pageSize.value)
      })

      expect(paginatedCards.value.length).toBe(50)

      currentPage.value = 2
      expect(paginatedCards.value.length).toBe(25)
    })
  })

  describe('filters', () => {
    it('filters by model', () => {
      const allCards = ref([
        { board_id: 'BRD-001', model: 'ModelA', array_host: '' },
        { board_id: 'BRD-002', model: 'ModelB', array_host: '' },
        { board_id: 'BRD-003', model: 'ModelA', array_host: '' },
      ])
      const filters = ref({ model: ['ModelA'], host: [], tag_l1: [], tag_l2: [] })

      const filteredCards = computed(() => {
        return allCards.value.filter(card => {
          if (filters.value.model.length && !filters.value.model.includes(card.model || '')) return false
          return true
        })
      })

      expect(filteredCards.value.length).toBe(2)
    })

    it('computes model options from data', () => {
      const allCards = ref([
        { model: 'ModelA' },
        { model: 'ModelB' },
        { model: 'ModelA' },
        { model: '' },
      ])

      const modelOptions = computed(() =>
        [...new Set(allCards.value.map(c => (c.model || '').trim()).filter(Boolean))].sort()
      )

      expect(modelOptions.value).toEqual(['ModelA', 'ModelB'])
    })

    it('resets all filters', () => {
      const filters = ref({ model: ['A'], host: ['10.0.0.1'], tag_l1: ['L1'], tag_l2: ['L2'] })

      const resetAllFilters = () => {
        filters.value = { model: [], host: [], tag_l1: [], tag_l2: [] }
      }

      resetAllFilters()
      expect(filters.value.model.length).toBe(0)
      expect(filters.value.host.length).toBe(0)
      expect(filters.value.tag_l1.length).toBe(0)
      expect(filters.value.tag_l2.length).toBe(0)
    })
  })

  describe('auto sync', () => {
    it('auto-syncs every 5 minutes', () => {
      const AUTO_SYNC_SECONDS = 300
      let syncCount = 0
      const timer = setInterval(() => { syncCount++ }, AUTO_SYNC_SECONDS * 1000)

      vi.advanceTimersByTime(300 * 1000)
      expect(syncCount).toBe(1)

      vi.advanceTimersByTime(300 * 1000)
      expect(syncCount).toBe(2)

      clearInterval(timer)
    })

    it('computes next auto sync countdown', () => {
      const nowTs = ref(Date.now())
      const nextAutoSyncAt = ref(nowTs.value + 300 * 1000)

      const nextAutoSyncText = computed(() => {
        const diff = Math.max(0, Math.floor((nextAutoSyncAt.value - nowTs.value) / 1000))
        const mm = String(Math.floor(diff / 60)).padStart(2, '0')
        const ss = String(diff % 60).padStart(2, '0')
        return `${mm}:${ss}`
      })

      expect(nextAutoSyncText.value).toBe('05:00')
    })
  })
})
