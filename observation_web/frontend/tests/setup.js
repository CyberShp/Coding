import { config } from '@vue/test-utils'
import { vi } from 'vitest'

// Mock Element Plus
config.global.stubs = {
  'el-button': true,
  'el-card': true,
  'el-row': true,
  'el-col': true,
  'el-icon': true,
  'el-empty': true,
  'el-table': true,
  'el-table-column': true,
  'el-tag': true,
  'el-switch': true,
  'el-radio-group': true,
  'el-radio-button': true,
  'el-pagination': true,
  'el-select': true,
  'el-option': true,
  'el-input': true,
  'el-form': true,
  'el-form-item': true,
  'el-drawer': true,
  'el-dialog': true,
  'el-message': true,
  'el-tooltip': true,
  'el-popover': true,
  'el-dropdown': true,
  'el-dropdown-menu': true,
  'el-dropdown-item': true,
  'v-chart': true,
}

// Mock vue-router
vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    go: vi.fn(),
    back: vi.fn(),
  }),
  useRoute: () => ({
    params: {},
    query: {},
    path: '/',
    name: '',
  }),
}))

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock WebSocket
global.WebSocket = vi.fn().mockImplementation(() => ({
  onopen: null,
  onclose: null,
  onmessage: null,
  onerror: null,
  send: vi.fn(),
  close: vi.fn(),
  readyState: 1,
}))
