<template>
  <div class="admin-login">
    <!-- Animated background light spots -->
    <div class="bg-spots">
      <span class="spot spot-1"></span>
      <span class="spot spot-2"></span>
      <span class="spot spot-3"></span>
    </div>

    <div class="login-container">
      <!-- Left: System description panel -->
      <div class="brand-panel">
        <div class="brand-header">
          <el-icon :size="28" class="brand-icon"><Monitor /></el-icon>
          <h1 class="brand-title">Observation Web<br /><span class="brand-title-zh">异常判读台</span></h1>
        </div>

        <p class="brand-desc">
          面向测试场景的异常判读台 — 告警准确、信息干净、反馈及时
        </p>

        <ul class="feature-list">
          <li><el-icon><Check /></el-icon>多维度告警聚合与自动降噪</li>
          <li><el-icon><Check /></el-icon>实时数据流监控与可视化</li>
          <li><el-icon><Check /></el-icon>灵活的自定义查询与报表导出</li>
          <li><el-icon><Check /></el-icon>细粒度权限管理与审计日志</li>
        </ul>

        <div class="brand-meta">
          <span class="meta-tag">v3.0.0</span>
          <span class="meta-divider">·</span>
          <span class="meta-text">Production</span>
        </div>
      </div>

      <!-- Right: Login card -->
      <div class="form-panel">
        <div class="login-card">
          <h2 class="card-title">管理员登录</h2>
          <p class="card-hint">仅管理员需要登录，普通用户默认只读访问</p>

          <form @submit.prevent="handleSubmit" class="login-form">
            <div class="form-field">
              <label class="field-label">账号</label>
              <input
                v-model="form.username"
                type="text"
                class="field-input"
                placeholder="请输入管理员账号"
                autocomplete="username"
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
                />
                <button
                  type="button"
                  class="eye-toggle"
                  @click="showPassword = !showPassword"
                  :title="showPassword ? '隐藏密码' : '显示密码'"
                >
                  <el-icon :size="16">
                    <View v-if="!showPassword" />
                    <Hide v-else />
                  </el-icon>
                </button>
              </div>
            </div>

            <button
              type="submit"
              class="submit-btn"
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
import { Monitor, Check, View, Hide } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const showPassword = ref(false)

const form = reactive({
  username: '',
  password: '',
})

async function handleSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请填写账号和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    ElMessage.success('登录成功')
    setTimeout(() => router.push('/settings'), 800)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '登录失败')
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
/* ---- Page layout ---- */
.admin-login {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f0f4f8 0%, #e2e8f0 50%, #edf1f7 100%);
  padding: 24px;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.login-container {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: stretch;
  max-width: 920px;
  width: 100%;
  min-height: 480px;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 40px rgba(15, 23, 42, 0.08), 0 1px 4px rgba(15, 23, 42, 0.04);
}

/* ---- Animated background spots ---- */
.bg-spots {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}

.spot {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.35;
}

.spot-1 {
  width: 420px;
  height: 420px;
  background: #93b5e1;
  top: -10%;
  left: -5%;
  animation: float-spot 18s ease-in-out infinite;
}

.spot-2 {
  width: 360px;
  height: 360px;
  background: #a8c5da;
  bottom: -8%;
  right: -4%;
  animation: float-spot 22s ease-in-out infinite reverse;
}

.spot-3 {
  width: 280px;
  height: 280px;
  background: #b4c6d4;
  top: 40%;
  left: 55%;
  animation: float-spot 15s ease-in-out infinite 3s;
}

@keyframes float-spot {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -20px) scale(1.05); }
  66% { transform: translate(-20px, 15px) scale(0.95); }
}

/* ---- Left brand panel ---- */
.brand-panel {
  flex: 1;
  background: linear-gradient(160deg, #0f172a 0%, #1e293b 100%);
  color: #e2e8f0;
  padding: 48px 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.brand-icon {
  color: #60a5fa;
  flex-shrink: 0;
}

.brand-title {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
  margin: 0;
  color: #f8fafc;
}

.brand-title-zh {
  font-size: 16px;
  font-weight: 400;
  color: #94a3b8;
}

.brand-desc {
  font-size: 14px;
  line-height: 1.7;
  color: #94a3b8;
  margin: 0 0 28px;
}

.feature-list {
  list-style: none;
  margin: 0 0 32px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #cbd5e1;
}

.feature-list li .el-icon {
  color: #60a5fa;
  flex-shrink: 0;
}

.brand-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
}

.meta-tag {
  font-size: 12px;
  font-weight: 600;
  color: #60a5fa;
  background: rgba(96, 165, 250, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
}

.meta-divider {
  color: #475569;
}

.meta-text {
  font-size: 12px;
  color: #64748b;
}

/* ---- Right form panel ---- */
.form-panel {
  flex: 0 0 380px;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 36px;
}

.login-card {
  width: 100%;
}

.card-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 8px;
}

.card-hint {
  font-size: 13px;
  color: #94a3b8;
  margin: 0 0 32px;
  line-height: 1.6;
}

/* ---- Form ---- */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 13px;
  font-weight: 500;
  color: #475569;
}

.field-input {
  width: 100%;
  border: 1.5px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  color: #0f172a;
  background: #f8fafc;
  outline: none;
  transition: border-color 0.25s, box-shadow 0.25s, background-color 0.25s;
  box-sizing: border-box;
}

.field-input::placeholder {
  color: #94a3b8;
}

.field-input:focus {
  border-color: #3b82f6;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.password-wrapper {
  position: relative;
}

.password-wrapper .field-input {
  padding-right: 40px;
}

.eye-toggle {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  transition: color 0.2s;
}

.eye-toggle:hover {
  color: #475569;
}

/* ---- Submit button ---- */
.submit-btn {
  width: 100%;
  padding: 12px;
  margin-top: 4px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #1e3a5f 0%, #1e293b 100%);
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 2px;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.1s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.submit-btn:hover:not(:disabled) {
  opacity: 0.9;
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
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ---- Footer ---- */
.card-footer {
  text-align: center;
  margin-top: 24px;
}

.back-link {
  font-size: 13px;
  color: #94a3b8;
  cursor: pointer;
  text-decoration: none;
  transition: color 0.2s;
}

.back-link:hover {
  color: #1e293b;
}

/* ---- Responsive ---- */
@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
    max-width: 420px;
  }

  .brand-panel {
    padding: 32px 28px;
  }

  .form-panel {
    flex: unset;
    padding: 32px 28px;
  }
}
</style>
