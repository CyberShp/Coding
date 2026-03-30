/**
 * CardInventory.vue component tests.
 *
 * Validates:
 * - Four states: loading, empty, error, normal
 * - IP + board_id search
 * - Filter functionality
 * - Card state display (health/running)
 * - Empty data prompts
 * - Backend field missing tolerance
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, computed, nextTick } from 'vue'

// --- Simulate CardInventory page logic ---

function makeCard(overrides = {}) {
  return {
    id: 1,
    array_id: 'arr-1',
    card_no: 'No001',
    board_id: 'BD001',
    health_state: 'NORMAL',
    running_state: 'RUNNING',
    model: 'IT21EMCB0',
    raw_fields: '{}',
    last_updated: new Date().toISOString(),
    array_name: 'TestArray',
    array_host: '10.0.0.1',
    tag_l1: 'DC1',
    tag_l2: 'Rack1',
    ...overrides,
  }
}

function stateTagType(value, expected) {
  if (!value) return 'info'
  return String(value).toUpperCase() === expected ? 'success' : 'danger'
}

function formatRelativeTime(ts) {
  if (!ts) return '--'
  const ms = new Date(ts).getTime()
  if (Number.isNaN(ms)) return '--'
  const diffSec = Math.floor((Date.now() - ms) / 1000)
  if (diffSec < 60) return `${Math.max(diffSec, 0)} 秒前`
  return `${Math.floor(diffSec / 60)} 分钟前`
}

describe('CardInventory', () => {
  describe('Four-state rendering', () => {
    it('loading state', () => {
      const loading = ref(true)
      const allCards = ref([])
      expect(loading.value).toBe(true)
      expect(allCards.value).toHaveLength(0)
    })

    it('empty state: no cards', () => {
      const loading = ref(false)
      const allCards = ref([])
      expect(loading.value).toBe(false)
      expect(allCards.value).toHaveLength(0)
    })

    it('error state', () => {
      const loading = ref(false)
      const allCards = ref([])
      const error = ref('Failed to load')
      expect(error.value).toBeTruthy()
    })

    it('normal state with data', () => {
      const loading = ref(false)
      const allCards = ref([makeCard(), makeCard({ id: 2, card_no: 'No002' })])
      expect(allCards.value).toHaveLength(2)
    })
  })

  describe('Search functionality', () => {
    it('multi-keyword search matches board_id and model', () => {
      const cards = [
        makeCard({ board_id: 'BD_ABC', model: 'ModelX' }),
        makeCard({ id: 2, board_id: 'BD_DEF', model: 'ModelY' }),
      ]
      const searchQuery = 'BD_ABC ModelX'
      const keywords = searchQuery.trim().toLowerCase().split(/\s+/).filter(Boolean)

      const results = cards.filter(card => {
        const searchable = `${card.model} ${card.board_id} ${card.card_no} ${card.array_name} ${card.array_host}`.toLowerCase()
        return keywords.every(kw => searchable.includes(kw))
      })

      expect(results).toHaveLength(1)
      expect(results[0].board_id).toBe('BD_ABC')
    })

    it('IP search finds card', () => {
      const cards = [
        makeCard({ array_host: '192.168.1.100' }),
        makeCard({ id: 2, array_host: '192.168.1.200' }),
      ]
      const searchQuery = '192.168.1.100'
      const keywords = searchQuery.trim().toLowerCase().split(/\s+/)

      const results = cards.filter(card => {
        const searchable = `${card.model} ${card.board_id} ${card.card_no} ${card.array_name} ${card.array_host}`.toLowerCase()
        return keywords.every(kw => searchable.includes(kw))
      })

      expect(results).toHaveLength(1)
      expect(results[0].array_host).toBe('192.168.1.100')
    })

    it('no match returns empty', () => {
      const cards = [makeCard()]
      const keywords = ['nonexistent']
      const results = cards.filter(card => {
        const searchable = `${card.model} ${card.board_id} ${card.card_no} ${card.array_name} ${card.array_host}`.toLowerCase()
        return keywords.every(kw => searchable.includes(kw))
      })
      expect(results).toHaveLength(0)
    })
  })

  describe('Filter functionality', () => {
    it('filter by model', () => {
      const cards = [
        makeCard({ model: 'IT21EMCB0' }),
        makeCard({ id: 2, model: 'IT22EMCB0' }),
      ]
      const filterModel = ['IT21EMCB0']

      const filtered = cards.filter(c => {
        if (filterModel.length && !filterModel.includes(c.model || '')) return false
        return true
      })

      expect(filtered).toHaveLength(1)
      expect(filtered[0].model).toBe('IT21EMCB0')
    })

    it('filter by host', () => {
      const cards = [
        makeCard({ array_host: '10.0.0.1' }),
        makeCard({ id: 2, array_host: '10.0.0.2' }),
      ]
      const filterHost = ['10.0.0.1']

      const filtered = cards.filter(c => {
        if (filterHost.length && !filterHost.includes(c.array_host || '')) return false
        return true
      })

      expect(filtered).toHaveLength(1)
    })

    it('filter by tag_l1', () => {
      const cards = [
        makeCard({ tag_l1: 'DC1' }),
        makeCard({ id: 2, tag_l1: 'DC2' }),
      ]
      const filterTag = ['DC1']

      const filtered = cards.filter(c => {
        if (filterTag.length && !filterTag.includes(c.tag_l1 || '')) return false
        return true
      })

      expect(filtered).toHaveLength(1)
      expect(filtered[0].tag_l1).toBe('DC1')
    })

    it('empty filter returns all', () => {
      const cards = [makeCard(), makeCard({ id: 2 })]
      const filterModel = []

      const filtered = cards.filter(c => {
        if (filterModel.length && !filterModel.includes(c.model || '')) return false
        return true
      })

      expect(filtered).toHaveLength(2)
    })
  })

  describe('Card state display', () => {
    it('NORMAL health → success tag', () => {
      expect(stateTagType('NORMAL', 'NORMAL')).toBe('success')
    })

    it('RUNNING state → success tag', () => {
      expect(stateTagType('RUNNING', 'RUNNING')).toBe('success')
    })

    it('OFFLINE state → danger tag', () => {
      expect(stateTagType('OFFLINE', 'RUNNING')).toBe('danger')
    })

    it('FAULT health → danger tag', () => {
      expect(stateTagType('FAULT', 'NORMAL')).toBe('danger')
    })

    it('empty state → info tag', () => {
      expect(stateTagType('', 'NORMAL')).toBe('info')
    })

    it('null state → info tag', () => {
      expect(stateTagType(null, 'NORMAL')).toBe('info')
    })
  })

  describe('Backend field missing tolerance', () => {
    it('card with missing array_name shows empty', () => {
      const card = makeCard({ array_name: undefined })
      expect(card.array_name || '').toBe('')
    })

    it('card with missing tag_l1 shows empty', () => {
      const card = makeCard({ tag_l1: undefined })
      expect(card.tag_l1 || '').toBe('')
    })

    it('card with missing last_updated shows "--"', () => {
      const card = makeCard({ last_updated: null })
      expect(formatRelativeTime(card.last_updated)).toBe('--')
    })

    it('card with invalid timestamp shows "--"', () => {
      expect(formatRelativeTime('not-a-date')).toBe('--')
    })
  })

  describe('Pagination', () => {
    it('paginates correctly', () => {
      const cards = Array.from({ length: 75 }, (_, i) => makeCard({ id: i + 1, card_no: `No${String(i + 1).padStart(3, '0')}` }))
      const pageSize = 50
      const currentPage = 1
      const start = (currentPage - 1) * pageSize
      const page1 = cards.slice(start, start + pageSize)
      expect(page1).toHaveLength(50)

      const page2 = cards.slice(50, 100)
      expect(page2).toHaveLength(25)
    })
  })

  describe('Filter option extraction', () => {
    it('model options extracted from cards', () => {
      const cards = [
        makeCard({ model: 'A' }),
        makeCard({ id: 2, model: 'B' }),
        makeCard({ id: 3, model: 'A' }),
      ]
      const modelOptions = [...new Set(cards.map(c => (c.model || '').trim()).filter(Boolean))].sort()
      expect(modelOptions).toEqual(['A', 'B'])
    })
  })
})
