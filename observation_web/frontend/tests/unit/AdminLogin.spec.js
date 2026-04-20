/**
 * AdminLogin.spec.js — real component interaction tests.
 *
 * All tests mount the actual AdminLogin component via shallowMount
 * and interact with real DOM elements (inputs, buttons, form).
 * No local-variable-only assertions.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import AdminLogin from '@/views/AdminLogin.vue'

// ---------------------------------------------------------------------------
// Stable mock references — vi.hoisted runs before vi.mock factories
// ---------------------------------------------------------------------------

const mockLogin = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('element-plus', () => ({
  ElMessage: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
}))

vi.mock('@element-plus/icons-vue', () => ({
  Monitor: { template: '<span />' },
  Check: { template: '<span />' },
  View: { template: '<span />' },
  Hide: { template: '<span />' },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    isAdmin: false,
    login: mockLogin,
  }),
}))

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AdminLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockLogin.mockResolvedValue(undefined) // restore after clearAllMocks
  })

  describe('renders', () => {
    it('mounts without errors', () => {
      const wrapper = shallowMount(AdminLogin)
      expect(wrapper.exists()).toBe(true)
    })

    it('renders a form with username and password inputs', () => {
      const wrapper = shallowMount(AdminLogin)
      expect(wrapper.find('form').exists()).toBe(true)

      const inputs = wrapper.findAll('input')
      const types = inputs.map(i => i.attributes('type') ?? 'text')
      expect(types).toContain('text')     // username field
      expect(types).toContain('password') // password field
    })

    it('submit button is enabled by default (loading=false)', () => {
      const wrapper = shallowMount(AdminLogin)
      const btn = wrapper.find('button[type="submit"]')
      expect(btn.exists()).toBe(true)
      expect(btn.attributes('disabled')).toBeUndefined()
    })
  })

  describe('form interaction', () => {
    it('accepts typed username and password via v-model', async () => {
      const wrapper = shallowMount(AdminLogin)
      const [usernameInput, passwordInput] = wrapper.findAll('input')

      await usernameInput.setValue('admin')
      await passwordInput.setValue('pass123')

      expect(usernameInput.element.value).toBe('admin')
      expect(passwordInput.element.value).toBe('pass123')
    })

    it('toggles password input type when eye button is clicked', async () => {
      const wrapper = shallowMount(AdminLogin)
      const passwordInput = wrapper.find('input[autocomplete="current-password"]')

      expect(passwordInput.attributes('type')).toBe('password')

      await wrapper.find('button.eye-toggle').trigger('click')
      await nextTick()

      expect(passwordInput.attributes('type')).toBe('text')

      // Toggle back
      await wrapper.find('button.eye-toggle').trigger('click')
      await nextTick()

      expect(passwordInput.attributes('type')).toBe('password')
    })
  })

  describe('form submission', () => {
    it('calls authStore.login with username and password on submit', async () => {
      const wrapper = shallowMount(AdminLogin)
      const [usernameInput, passwordInput] = wrapper.findAll('input')

      await usernameInput.setValue('admin')
      await passwordInput.setValue('secret')
      await wrapper.find('form').trigger('submit')
      await nextTick()

      expect(mockLogin).toHaveBeenCalledOnce()
      expect(mockLogin).toHaveBeenCalledWith('admin', 'secret')
    })

    it('shows ElMessage.warning and does NOT call login when fields are empty', async () => {
      const wrapper = shallowMount(AdminLogin)
      await wrapper.find('form').trigger('submit')
      await nextTick()

      expect(ElMessage.warning).toHaveBeenCalled()
      expect(mockLogin).not.toHaveBeenCalled()
    })

    it('shows ElMessage.error with server detail when login rejects', async () => {
      mockLogin.mockRejectedValueOnce({
        response: { data: { detail: '用户名或密码错误' } },
      })

      const wrapper = shallowMount(AdminLogin)
      const [usernameInput, passwordInput] = wrapper.findAll('input')
      await usernameInput.setValue('admin')
      await passwordInput.setValue('badpass')
      await wrapper.find('form').trigger('submit')
      await nextTick()
      await nextTick() // extra tick for async catch block

      expect(ElMessage.error).toHaveBeenCalledWith('用户名或密码错误')
    })

    it('falls back to generic error when response has no detail', async () => {
      mockLogin.mockRejectedValueOnce(new Error('Network error'))

      const wrapper = shallowMount(AdminLogin)
      const [usernameInput, passwordInput] = wrapper.findAll('input')
      await usernameInput.setValue('admin')
      await passwordInput.setValue('badpass')
      await wrapper.find('form').trigger('submit')
      await nextTick()
      await nextTick()

      expect(ElMessage.error).toHaveBeenCalledWith('登录失败')
    })
  })
})
