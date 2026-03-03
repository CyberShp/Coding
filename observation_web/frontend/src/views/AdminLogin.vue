<template>
  <div class="admin-login" @mousemove="onMouseMove" @mouseleave="onMouseLeave">
    <div class="login-container">
      <!-- Left: Blob mascots group -->
      <div class="mascots-area">
        <div class="mascots-group">
          <div class="mascot-slot slot-purple">
            <PixelPet character="purple" :mood="mood" :look-at="lookAt" />
          </div>
          <div class="mascot-slot slot-orange">
            <PixelPet character="orange" :mood="mood" :look-at="lookAt" />
          </div>
          <div class="mascot-slot slot-yellow">
            <PixelPet character="yellow" :mood="mood" :look-at="lookAt" />
          </div>
        </div>
      </div>

      <!-- Right: Login form card -->
      <div class="form-area">
        <div class="login-card">
          <div class="card-icon">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </div>

          <h2 class="card-title">欢迎回来!</h2>
          <p class="card-subtitle">请输入管理员凭据</p>

          <form @submit.prevent="handleSubmit" class="login-form">
            <div class="form-field">
              <label class="field-label">账号</label>
              <input
                v-model="form.username"
                type="text"
                class="field-input"
                placeholder="请输入账号"
                autocomplete="username"
                @focus="mood = 'watching'"
                @blur="onInputBlur('username')"
              />
            </div>

            <div class="form-field">
              <label class="field-label">密码</label>
              <div class="password-wrapper">
                <input
                  v-model="form.password"
                  :type="showPassword ? 'text' : 'password'"
                  class="field-input"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                  @focus="mood = 'watching'"
                  @blur="onInputBlur('password')"
                />
                <button
                  type="button"
                  class="eye-toggle"
                  @click="onTogglePassword"
                  :title="showPassword ? '隐藏密码' : '显示密码'"
                >
                  <svg v-if="!showPassword" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#999" stroke-width="1.8">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#999" stroke-width="1.8">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                </button>
              </div>
            </div>

            <button
              type="submit"
              class="submit-btn"
              :class="{ 'is-loading': loading }"
              :disabled="loading"
            >
              <span v-if="loading" class="btn-spinner"></span>
              <span v-else>登录</span>
            </button>
          </form>

          <div class="card-footer">
            <a class="back-link" @click.prevent="$router.push('/settings')">← 返回设置</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PixelPet from '../components/PixelPet.vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const mood = ref('idle')
const lookAt = ref({ x: 0.5, y: 0.5 })
const showPassword = ref(false)

const form = reactive({
  username: '',
  password: '',
})

function onMouseMove(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  lookAt.value = {
    x: (e.clientX - rect.left) / rect.width,
    y: (e.clientY - rect.top) / rect.height,
  }
}

function onMouseLeave() {
  lookAt.value = { x: 0.5, y: 0.5 }
}

function onInputBlur(field) {
  if (field === 'username' && !form.password) mood.value = 'idle'
  if (field === 'password' && !form.username) mood.value = 'idle'
}

function onTogglePassword() {
  showPassword.value = !showPassword.value
  if (showPassword.value) {
    mood.value = 'hiding'
    setTimeout(() => {
      if (mood.value === 'hiding') mood.value = 'watching'
    }, 1500)
  }
}

async function handleSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请填写账号和密码')
    return
  }
  loading.value = true
  mood.value = 'watching'
  try {
    await authStore.login(form.username, form.password)
    mood.value = 'success'
    ElMessage.success('登录成功')
    setTimeout(() => router.push('/settings'), 800)
  } catch (err) {
    mood.value = 'error'
    ElMessage.error(err.response?.data?.detail || '登录失败')
    setTimeout(() => { mood.value = 'watching' }, 1500)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (authStore.isAdmin) {
    router.replace('/settings')
  }
})
</script>

<style scoped>
.admin-login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f0;
  padding: 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.login-container {
  display: flex;
  align-items: center;
  gap: 60px;
  max-width: 860px;
  width: 100%;
}

/* ---- Mascots ---- */
.mascots-area {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: flex-end;
  min-width: 320px;
}

.mascots-group {
  position: relative;
  width: 320px;
  height: 260px;
}

.mascot-slot {
  position: absolute;
  bottom: 0;
}

.slot-purple {
  width: 110px;
  height: 200px;
  left: 55px;
  bottom: 0;
  z-index: 1;
}

.slot-orange {
  width: 190px;
  height: 140px;
  left: 0;
  bottom: 0;
  z-index: 2;
}

.slot-yellow {
  width: 120px;
  height: 160px;
  right: 10px;
  bottom: 0;
  z-index: 1;
}

/* ---- Form Card ---- */
.form-area {
  flex: 0 0 340px;
}

.login-card {
  background: white;
  border-radius: 16px;
  padding: 36px 32px 28px;
  box-shadow: 0 2px 24px rgba(0, 0, 0, 0.06);
}

.card-icon {
  width: 36px;
  height: 36px;
  margin: 0 auto 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #333;
}

.card-title {
  text-align: center;
  font-size: 22px;
  font-weight: 700;
  color: #1a1a1a;
  margin: 0 0 6px;
}

.card-subtitle {
  text-align: center;
  font-size: 13px;
  color: #888;
  margin: 0 0 28px;
}

/* ---- Form Fields ---- */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 13px;
  font-weight: 500;
  color: #555;
}

.field-input {
  width: 100%;
  border: none;
  border-bottom: 1.5px solid #e0e0e0;
  padding: 8px 0;
  font-size: 14px;
  color: #1a1a1a;
  background: transparent;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.field-input::placeholder {
  color: #c0c0c0;
}

.field-input:focus {
  border-bottom-color: #1a1a1a;
}

.password-wrapper {
  position: relative;
}

.password-wrapper .field-input {
  padding-right: 36px;
}

.eye-toggle {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.eye-toggle:hover {
  opacity: 1;
}

/* ---- Submit Button ---- */
.submit-btn {
  width: 100%;
  padding: 12px;
  margin-top: 8px;
  border: none;
  border-radius: 8px;
  background: #1a1a2e;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s, transform 0.1s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.submit-btn:hover:not(:disabled) {
  background: #2d2d4a;
}

.submit-btn:active:not(:disabled) {
  transform: scale(0.98);
}

.submit-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.btn-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ---- Footer ---- */
.card-footer {
  text-align: center;
  margin-top: 20px;
}

.back-link {
  font-size: 13px;
  color: #888;
  cursor: pointer;
  text-decoration: none;
  transition: color 0.2s;
}

.back-link:hover {
  color: #1a1a1a;
}

/* ---- Responsive ---- */
@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
    gap: 32px;
  }

  .mascots-area {
    min-width: unset;
  }

  .mascots-group {
    width: 260px;
    height: 210px;
  }

  .slot-purple {
    width: 90px;
    height: 165px;
    left: 45px;
  }

  .slot-orange {
    width: 155px;
    height: 115px;
  }

  .slot-yellow {
    width: 100px;
    height: 130px;
    right: 5px;
  }

  .form-area {
    flex: unset;
    width: 100%;
    max-width: 340px;
  }
}
</style>
