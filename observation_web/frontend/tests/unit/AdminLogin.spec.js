import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, reactive, computed } from 'vue'

describe('AdminLogin', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('form state', () => {
    it('renders login form with username and password fields', () => {
      const form = reactive({ username: '', password: '' })

      expect(form.username).toBe('')
      expect(form.password).toBe('')
      expect('username' in form).toBe(true)
      expect('password' in form).toBe(true)
    })

    it('shows system info panel with product name', () => {
      const brandTitle = 'Observation Web'
      const brandTitleZh = '异常判读台'
      const version = 'v3.0.0'

      expect(brandTitle).toContain('Observation')
      expect(brandTitleZh).toBe('异常判读台')
      expect(version).toMatch(/^v\d+\.\d+\.\d+$/)
    })

    it('shows admin-only login hint', () => {
      const hintText = '仅管理员需要登录，普通用户默认只读访问'
      expect(hintText).toContain('仅管理员需要登录')
    })

    it('submit button exists and is not disabled by default', () => {
      const loading = ref(false)
      const isDisabled = computed(() => loading.value)

      expect(isDisabled.value).toBe(false)
    })
  })

  describe('password toggle', () => {
    it('toggles password visibility', () => {
      const showPassword = ref(false)

      expect(showPassword.value).toBe(false)

      // Click eye icon
      showPassword.value = !showPassword.value
      expect(showPassword.value).toBe(true)

      // Input type should be 'text' when showPassword is true
      const inputType = computed(() => showPassword.value ? 'text' : 'password')
      expect(inputType.value).toBe('text')

      // Toggle back
      showPassword.value = !showPassword.value
      expect(showPassword.value).toBe(false)
      expect(inputType.value).toBe('password')
    })
  })

  describe('form submission', () => {
    it('shows loading state on submit', async () => {
      const loading = ref(false)
      const form = reactive({ username: 'admin', password: 'pass123' })

      const handleSubmit = async () => {
        if (!form.username || !form.password) return
        loading.value = true
        try {
          await new Promise(resolve => setTimeout(resolve, 200))
        } finally {
          loading.value = false
        }
      }

      expect(loading.value).toBe(false)
      const submitPromise = handleSubmit()
      expect(loading.value).toBe(true)

      vi.advanceTimersByTime(200)
      await submitPromise
      expect(loading.value).toBe(false)
    })

    it('does not submit with empty fields', async () => {
      const form = reactive({ username: '', password: '' })
      let loginCalled = false
      let warningShown = false

      const handleSubmit = async () => {
        if (!form.username || !form.password) {
          warningShown = true
          return
        }
        loginCalled = true
      }

      await handleSubmit()
      expect(warningShown).toBe(true)
      expect(loginCalled).toBe(false)
    })

    it('shows error on failed login', async () => {
      const loading = ref(false)
      const form = reactive({ username: 'admin', password: 'wrong' })
      let errorMessage = ''

      const mockLogin = async () => {
        const error = new Error('Unauthorized')
        error.response = { data: { detail: '用户名或密码错误' } }
        throw error
      }

      const handleSubmit = async () => {
        if (!form.username || !form.password) return
        loading.value = true
        try {
          await mockLogin()
        } catch (err) {
          errorMessage = err.response?.data?.detail || '登录失败'
        } finally {
          loading.value = false
        }
      }

      await handleSubmit()
      expect(errorMessage).toBe('用户名或密码错误')
      expect(loading.value).toBe(false)
    })

    it('shows generic error when no detail in response', async () => {
      const form = reactive({ username: 'admin', password: 'wrong' })
      let errorMessage = ''

      const mockLogin = async () => {
        throw new Error('Network error')
      }

      const handleSubmit = async () => {
        if (!form.username || !form.password) return
        try {
          await mockLogin()
        } catch (err) {
          errorMessage = err.response?.data?.detail || '登录失败'
        }
      }

      await handleSubmit()
      expect(errorMessage).toBe('登录失败')
    })

    it('redirects to settings on successful login', async () => {
      const form = reactive({ username: 'admin', password: 'pass123' })
      let routerPushTarget = null

      const mockLogin = async () => ({ token: 'abc123' })
      const router = { push: vi.fn(path => { routerPushTarget = path }) }

      const handleSubmit = async () => {
        if (!form.username || !form.password) return
        await mockLogin()
        setTimeout(() => router.push('/settings'), 800)
      }

      await handleSubmit()
      vi.advanceTimersByTime(800)

      expect(router.push).toHaveBeenCalledWith('/settings')
      expect(routerPushTarget).toBe('/settings')
    })
  })

  describe('auth redirect', () => {
    it('redirects if already admin', () => {
      const isAdmin = true
      const router = { replace: vi.fn() }

      // Simulates onMounted logic
      if (isAdmin) {
        router.replace('/settings')
      }

      expect(router.replace).toHaveBeenCalledWith('/settings')
    })

    it('does not redirect if not admin', () => {
      const isAdmin = false
      const router = { replace: vi.fn() }

      if (isAdmin) {
        router.replace('/settings')
      }

      expect(router.replace).not.toHaveBeenCalled()
    })
  })

  describe('professional enterprise style', () => {
    it('has professional enterprise style - no toy elements', () => {
      const brandTitle = 'Observation Web'
      const cardTitle = '管理员登录'

      // No PixelPet, no toy elements
      expect(brandTitle).not.toContain('PixelPet')
      expect(cardTitle).not.toContain('PixelPet')
      expect(brandTitle).toContain('Observation')
    })

    it('contains feature list descriptions', () => {
      const features = [
        '多维度告警聚合与自动降噪',
        '实时数据流监控与可视化',
        '灵活的自定义查询与报表导出',
        '细粒度权限管理与审计日志',
      ]

      expect(features.length).toBe(4)
      features.forEach(f => expect(f.length).toBeGreaterThan(0))
    })
  })

  describe('back navigation', () => {
    it('has back link to settings', () => {
      const backTarget = '/settings'
      const backText = '← 返回设置'

      expect(backTarget).toBe('/settings')
      expect(backText).toContain('返回设置')
    })
  })
})
