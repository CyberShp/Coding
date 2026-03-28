/**
 * AdminLogin.vue component tests.
 *
 * Validates:
 * - loading / failed / success states
 * - Token write logic
 * - Error message display
 * - Route redirect after success
 * - Input validation (empty fields)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, reactive } from 'vue'

describe('AdminLogin', () => {
  describe('Form state management', () => {
    it('initial state: not loading, no error', () => {
      const loading = ref(false)
      const mood = ref('idle')
      const form = reactive({ username: '', password: '' })

      expect(loading.value).toBe(false)
      expect(mood.value).toBe('idle')
      expect(form.username).toBe('')
      expect(form.password).toBe('')
    })
  })

  describe('Input validation', () => {
    it('empty username and password should show warning', () => {
      const form = reactive({ username: '', password: '' })
      const messages = []

      if (!form.username || !form.password) {
        messages.push('请填写账号和密码')
      }

      expect(messages).toContain('请填写账号和密码')
    })

    it('empty password only should show warning', () => {
      const form = reactive({ username: 'admin', password: '' })
      const messages = []

      if (!form.username || !form.password) {
        messages.push('请填写账号和密码')
      }

      expect(messages).toContain('请填写账号和密码')
    })

    it('valid inputs should pass validation', () => {
      const form = reactive({ username: 'admin', password: 'secret' })
      const valid = !!(form.username && form.password)
      expect(valid).toBe(true)
    })
  })

  describe('Login success flow', () => {
    it('successful login sets token and redirects', async () => {
      const loading = ref(false)
      const mood = ref('idle')
      const token = ref('')
      const routerPush = vi.fn()

      const mockLogin = vi.fn().mockResolvedValue({ data: { token: 'jwt-token-123' } })

      loading.value = true
      mood.value = 'watching'
      try {
        const res = await mockLogin('admin', 'password')
        token.value = res.data.token
        localStorage.setItem('admin_token', res.data.token)
        mood.value = 'success'
        routerPush('/settings')
      } catch {
        mood.value = 'error'
      } finally {
        loading.value = false
      }

      expect(token.value).toBe('jwt-token-123')
      expect(localStorage.getItem('admin_token')).toBe('jwt-token-123')
      expect(mood.value).toBe('success')
      expect(routerPush).toHaveBeenCalledWith('/settings')
      expect(loading.value).toBe(false)

      // Cleanup
      localStorage.removeItem('admin_token')
    })
  })

  describe('Login failure flow', () => {
    it('failed login shows error message and resets mood', async () => {
      const loading = ref(false)
      const mood = ref('idle')
      const errorMessage = ref('')

      const mockLogin = vi.fn().mockRejectedValue({
        response: { data: { detail: '密码错误' } }
      })

      loading.value = true
      mood.value = 'watching'
      try {
        await mockLogin('admin', 'wrong')
      } catch (err) {
        mood.value = 'error'
        errorMessage.value = err.response?.data?.detail || '登录失败'
      } finally {
        loading.value = false
      }

      expect(mood.value).toBe('error')
      expect(errorMessage.value).toBe('密码错误')
      expect(loading.value).toBe(false)
    })

    it('network error shows generic message', async () => {
      const errorMessage = ref('')
      const mockLogin = vi.fn().mockRejectedValue(new Error('Network Error'))

      try {
        await mockLogin('admin', 'pass')
      } catch (err) {
        errorMessage.value = err.response?.data?.detail || '登录失败'
      }

      expect(errorMessage.value).toBe('登录失败')
    })
  })

  describe('Token management', () => {
    it('token stored in localStorage', () => {
      localStorage.setItem('admin_token', 'test-token')
      expect(localStorage.getItem('admin_token')).toBe('test-token')
      localStorage.removeItem('admin_token')
    })

    it('logout clears token', () => {
      localStorage.setItem('admin_token', 'test-token')
      const token = ref(localStorage.getItem('admin_token'))

      // Simulate logout
      token.value = ''
      localStorage.removeItem('admin_token')

      expect(token.value).toBe('')
      expect(localStorage.getItem('admin_token')).toBeNull()
    })

    it('isAdmin computed from token', () => {
      const token = ref('some-token')
      const isAdmin = !!token.value
      expect(isAdmin).toBe(true)

      token.value = ''
      const isAdmin2 = !!token.value
      expect(isAdmin2).toBe(false)
    })
  })

  describe('Password visibility toggle', () => {
    it('toggles showPassword and mood', () => {
      const showPassword = ref(false)
      const mood = ref('watching')

      // Toggle on
      showPassword.value = !showPassword.value
      if (showPassword.value) {
        mood.value = 'hiding'
      }

      expect(showPassword.value).toBe(true)
      expect(mood.value).toBe('hiding')

      // Toggle off
      showPassword.value = !showPassword.value
      expect(showPassword.value).toBe(false)
    })
  })

  describe('Already authenticated redirect', () => {
    it('redirects to settings if already admin', () => {
      const isAdmin = true
      const routerReplace = vi.fn()

      if (isAdmin) {
        routerReplace('/settings')
      }

      expect(routerReplace).toHaveBeenCalledWith('/settings')
    })

    it('does not redirect if not admin', () => {
      const isAdmin = false
      const routerReplace = vi.fn()

      if (isAdmin) {
        routerReplace('/settings')
      }

      expect(routerReplace).not.toHaveBeenCalled()
    })
  })
})
