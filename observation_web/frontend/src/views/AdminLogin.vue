<template>
  <div class="admin-login" @mousemove="onMouseMove" @mouseleave="onMouseLeave">
    <div class="login-container">
      <!-- Left: Pixel pets -->
      <div class="pets-area">
        <div class="pets-row">
          <PixelPet
            v-for="(_, i) in 3"
            :key="i"
            :mood="mood"
            :look-at="lookAt"
            :offset="i"
          />
        </div>
      </div>

      <!-- Right: Login form -->
      <div class="form-area">
        <el-card class="login-card">
          <template #header>
            <span class="card-title">管理员登录</span>
          </template>
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-position="top"
            @submit.prevent="handleSubmit"
          >
            <el-form-item label="账号" prop="username">
              <el-input
                v-model="form.username"
                placeholder="请输入账号"
                @focus="mood = 'watching'"
                @blur="onInputBlur('username')"
              />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="请输入密码"
                @focus="mood = 'watching'"
                @blur="onInputBlur('password')"
              />
              <el-checkbox v-model="showPassword" @change="onShowPasswordChange" style="margin-top: 8px">
                显示密码
              </el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                class="submit-btn"
                :loading="loading"
                @click="handleSubmit"
              >
                登录
              </el-button>
              <el-button @click="$router.push('/settings')">返回设置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
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
import api from '../api'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const loading = ref(false)
const mood = ref('idle') // idle | watching | hiding | error | success
const lookAt = ref({ x: 0.5, y: 0.5 })
const showPassword = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function onMouseMove(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  lookAt.value = {
    x: (e.clientX - rect.left) / rect.width,
    y: (e.clientY - rect.top) / rect.height,
  }
  if (mood.value === 'idle' && !form.username && !form.password) {
    mood.value = 'idle'
  }
}

function onMouseLeave() {
  lookAt.value = { x: 0.5, y: 0.5 }
}

function onInputBlur(field) {
  if (field === 'username' && !form.password) mood.value = 'idle'
  if (field === 'password' && !form.username) mood.value = 'idle'
}

function onShowPasswordChange(visible) {
  if (visible) {
    mood.value = 'hiding'
    setTimeout(() => {
      if (mood.value === 'hiding') mood.value = 'watching'
    }, 1500)
  }
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    mood.value = 'watching'
    try {
      await authStore.login(form.username, form.password)
      mood.value = 'success'
      ElMessage.success('登录成功')
      setTimeout(() => {
        router.push('/settings')
      }, 800)
    } catch (err) {
      mood.value = 'error'
      ElMessage.error(err.response?.data?.detail || '登录失败')
      setTimeout(() => {
        mood.value = 'watching'
      }, 1500)
    } finally {
      loading.value = false
    }
  })
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
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  padding: 20px;
}

.login-container {
  display: flex;
  align-items: center;
  gap: 60px;
  max-width: 900px;
  width: 100%;
}

.pets-area {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
}

.pets-row {
  display: flex;
  gap: 24px;
  align-items: flex-end;
}

.form-area {
  flex: 1;
  max-width: 360px;
}

.login-card {
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.card-title {
  font-size: 20px;
  font-weight: 600;
}

.submit-btn {
  width: 100%;
}

@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
  }
  .pets-row {
    flex-wrap: wrap;
    justify-content: center;
  }
}
</style>
