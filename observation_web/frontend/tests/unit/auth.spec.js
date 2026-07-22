/**
 * auth.spec.js — multi-user Phase 1 frontend tests.
 *
 * Covers:
 *  - auth store: user login/register/logout + user_token localStorage persistence
 *  - API 401 handling: detail=login_required emits global event (no admin redirect)
 *  - authEvents bus semantics (on/off/emit)
 *  - TeamSelector: filters tags to level === 1
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// jsdom in this project runs on an opaque origin, so window.localStorage is a
// method-less stub. Install a functional in-memory implementation before any
// module under test touches it.
const memoryStorage = (() => {
  let store = {}
  return {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: k => { delete store[k] },
    clear: () => { store = {} },
  }
})()
Object.defineProperty(window, 'localStorage', { value: memoryStorage, writable: true })
import { createPinia, setActivePinia } from 'pinia'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'

import authEvents, { AUTH_LOGIN_REQUIRED } from '@/utils/authEvents'
import { handleError } from '@/api'
import { useAuthStore } from '@/stores/auth'
import TeamSelector from '@/components/auth/TeamSelector.vue'

// ---------------------------------------------------------------------------
// Mocks — keep handleError/extractError real, stub the endpoint methods
// ---------------------------------------------------------------------------

const mockApi = vi.hoisted(() => ({
  userLogin: vi.fn(),
  register: vi.fn(),
  whoami: vi.fn(),
  setMyTeams: vi.fn(),
  getTags: vi.fn(),
  login: vi.fn(),
  getAuthMe: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: { ...actual.default, ...mockApi },
  }
})

vi.mock('element-plus', () => ({
  ElMessage: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
}))

// ---------------------------------------------------------------------------
// authEvents bus
// ---------------------------------------------------------------------------

describe('authEvents bus', () => {
  it('emit delivers payload to registered listener', () => {
    // Arrange
    const handler = vi.fn()
    authEvents.on('test-evt', handler)

    // Act
    authEvents.emit('test-evt', { a: 1 })

    // Assert
    expect(handler).toHaveBeenCalledOnce()
    expect(handler).toHaveBeenCalledWith({ a: 1 })
    authEvents.off('test-evt', handler)
  })

  it('off removes the listener so later emits are not delivered', () => {
    // Arrange
    const handler = vi.fn()
    authEvents.on('test-evt-2', handler)
    authEvents.off('test-evt-2', handler)

    // Act
    authEvents.emit('test-evt-2')

    // Assert
    expect(handler).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// API 401 handling
// ---------------------------------------------------------------------------

describe('api handleError 401 handling', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('401 with detail=login_required emits AUTH_LOGIN_REQUIRED and keeps admin_token', async () => {
    // Arrange
    localStorage.setItem('admin_token', 'legacy-admin')
    const listener = vi.fn()
    authEvents.on(AUTH_LOGIN_REQUIRED, listener)
    const error = {
      response: { status: 401, data: { detail: 'login_required' } },
      config: { url: '/alerts/ack' },
    }

    // Act
    await expect(handleError(error)).rejects.toBe(error)

    // Assert — event emitted, no admin token clearing / redirect path taken
    expect(listener).toHaveBeenCalledOnce()
    expect(listener).toHaveBeenCalledWith({ url: '/alerts/ack' })
    expect(localStorage.getItem('admin_token')).toBe('legacy-admin')
    authEvents.off(AUTH_LOGIN_REQUIRED, listener)
  })

  it('401 without login_required does NOT emit the event (legacy admin path)', async () => {
    // Arrange — no admin_token stored, so legacy path is a no-op (no redirect)
    const listener = vi.fn()
    authEvents.on(AUTH_LOGIN_REQUIRED, listener)
    const error = { response: { status: 401, data: { detail: 'invalid token' } } }

    // Act
    await expect(handleError(error)).rejects.toBe(error)

    // Assert
    expect(listener).not.toHaveBeenCalled()
    authEvents.off(AUTH_LOGIN_REQUIRED, listener)
  })

  it('listener registered like App.vue opens dialog when event fires', () => {
    // Arrange — simulates App.vue wiring: event -> show LoginDialog
    let dialogVisible = false
    const openDialog = () => { dialogVisible = true }
    authEvents.on(AUTH_LOGIN_REQUIRED, openDialog)

    // Act
    authEvents.emit(AUTH_LOGIN_REQUIRED, {})

    // Assert
    expect(dialogVisible).toBe(true)
    authEvents.off(AUTH_LOGIN_REQUIRED, openDialog)
  })
})

// ---------------------------------------------------------------------------
// auth store — multi-user accounts
// ---------------------------------------------------------------------------

describe('auth store multi-user accounts', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('userLogin stores token in state and localStorage and sets currentUser', async () => {
    // Arrange
    mockApi.userLogin.mockResolvedValue({
      data: { token: 'tok-user-1', user: { id: 7, nickname: '小明', is_admin: false } },
    })
    const store = useAuthStore()

    // Act
    await store.userLogin('小明', 'pw123')

    // Assert
    expect(mockApi.userLogin).toHaveBeenCalledWith('小明', 'pw123')
    expect(store.userToken).toBe('tok-user-1')
    expect(localStorage.getItem('user_token')).toBe('tok-user-1')
    expect(store.isLoggedIn).toBe(true)
    expect(store.currentUser.nickname).toBe('小明')
  })

  it('register stores token and user like login', async () => {
    // Arrange
    mockApi.register.mockResolvedValue({
      data: { token: 'tok-new', user: { id: 8, nickname: '新人', is_admin: true } },
    })
    const store = useAuthStore()

    // Act
    await store.register('新人', 'pw456')

    // Assert
    expect(store.userToken).toBe('tok-new')
    expect(localStorage.getItem('user_token')).toBe('tok-new')
    expect(store.currentUser.is_admin).toBe(true)
  })

  it('userLogout clears token, currentUser and localStorage', async () => {
    // Arrange
    mockApi.userLogin.mockResolvedValue({
      data: { token: 'tok-x', user: { id: 1, nickname: 'a', is_admin: false } },
    })
    const store = useAuthStore()
    await store.userLogin('a', 'b')

    // Act
    store.userLogout()

    // Assert
    expect(store.userToken).toBe('')
    expect(store.currentUser).toBe(null)
    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem('user_token')).toBe(null)
  })

  it('userToken is restored from localStorage on store creation (persistence)', () => {
    // Arrange
    localStorage.setItem('user_token', 'persisted-tok')

    // Act — fresh pinia so the store setup re-reads localStorage
    setActivePinia(createPinia())
    const store = useAuthStore()

    // Assert
    expect(store.userToken).toBe('persisted-tok')
    expect(store.isLoggedIn).toBe(true)
  })

  it('fetchWhoami with anonymous response drops the stale token', async () => {
    // Arrange
    localStorage.setItem('user_token', 'stale-tok')
    setActivePinia(createPinia())
    mockApi.whoami.mockResolvedValue({ data: { anonymous: true } })
    const store = useAuthStore()

    // Act
    const result = await store.fetchWhoami()

    // Assert
    expect(result).toBe(null)
    expect(store.userToken).toBe('')
    expect(localStorage.getItem('user_token')).toBe(null)
  })

  it('fetchWhoami populates currentUser with teams', async () => {
    // Arrange
    localStorage.setItem('user_token', 'good-tok')
    setActivePinia(createPinia())
    mockApi.whoami.mockResolvedValue({
      data: { id: 3, nickname: '组员', is_admin: false, teams: [11, 12] },
    })
    const store = useAuthStore()

    // Act
    await store.fetchWhoami()

    // Assert
    expect(store.currentUser.nickname).toBe('组员')
    expect(store.currentUser.teams).toEqual([11, 12])
  })

  it('setTeams calls API and updates currentUser.teams', async () => {
    // Arrange
    mockApi.userLogin.mockResolvedValue({
      data: { token: 't', user: { id: 1, nickname: 'a', is_admin: false } },
    })
    mockApi.setMyTeams.mockResolvedValue({ data: { ok: true } })
    const store = useAuthStore()
    await store.userLogin('a', 'b')

    // Act
    await store.setTeams([5, 9])

    // Assert
    expect(mockApi.setMyTeams).toHaveBeenCalledWith([5, 9])
    expect(store.currentUser.teams).toEqual([5, 9])
  })

  it('admin login/logout still uses admin_token and is unaffected by user token', async () => {
    // Arrange
    mockApi.login.mockResolvedValue({ data: { token: 'admin-tok' } })
    const store = useAuthStore()

    // Act
    await store.login('admin', 'pw')

    // Assert
    expect(store.token).toBe('admin-tok')
    expect(localStorage.getItem('admin_token')).toBe('admin-tok')
    expect(store.isLoggedIn).toBe(false) // user account not logged in

    store.logout()
    expect(localStorage.getItem('admin_token')).toBe(null)
  })
})

// ---------------------------------------------------------------------------
// TeamSelector — level 1 tag filtering
// ---------------------------------------------------------------------------

describe('TeamSelector', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('level1Tags contains only tags with level === 1', async () => {
    // Arrange
    mockApi.getTags.mockResolvedValue({
      data: [
        { id: 1, name: '网络', level: 1 },
        { id: 2, name: '网络-交换', level: 2 },
        { id: 3, name: '前端', level: 1 },
        { id: 4, name: '细分组', level: 2 },
      ],
    })
    const wrapper = shallowMount(TeamSelector, {
      props: { modelValue: true },
    })

    // Act
    await wrapper.vm.loadTags()
    await nextTick()

    // Assert
    expect(wrapper.vm.level1Tags.map(t => t.id)).toEqual([1, 3])
    expect(wrapper.vm.level1Tags.every(t => t.level === 1)).toBe(true)
  })

  it('loadTags preselects the current user teams', async () => {
    // Arrange — user already in team 3
    const store = useAuthStore()
    store.currentUser = { id: 1, nickname: 'a', is_admin: false, teams: [3] }
    mockApi.getTags.mockResolvedValue({ data: [{ id: 3, name: '前端', level: 1 }] })
    const wrapper = shallowMount(TeamSelector, {
      props: { modelValue: true },
    })

    // Act
    await wrapper.vm.loadTags()

    // Assert
    expect(wrapper.vm.selectedIds).toEqual([3])
  })
})
