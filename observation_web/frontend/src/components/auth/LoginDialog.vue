<template>
  <el-dialog
    v-model="visible"
    :title="mode === 'login' ? '登录' : '注册'"
    width="380px"
    @closed="resetForm"
  >
    <p v-if="fromLoginRequired" class="login-hint">此操作需要登录后才能执行</p>

    <el-tabs v-model="mode" class="auth-tabs">
      <el-tab-pane label="登录" name="login" />
      <el-tab-pane label="注册" name="register" />
    </el-tabs>

    <el-form label-position="top" @submit.prevent="handleSubmit">
      <el-form-item label="昵称">
        <el-input
          v-model="nickname"
          placeholder="输入昵称"
          maxlength="20"
          autocomplete="username"
        />
      </el-form-item>
      <el-form-item label="口令">
        <el-input
          v-model="password"
          type="password"
          placeholder="输入口令"
          show-password
          autocomplete="current-password"
          @keyup.enter="handleSubmit"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">
        {{ mode === 'login' ? '登录' : '注册' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../stores/auth'
import { extractError } from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // true when the dialog was opened by a 401 login_required event
  fromLoginRequired: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'success'])

const authStore = useAuthStore()

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const mode = ref('login')
const nickname = ref('')
const password = ref('')
const loading = ref(false)

function resetForm() {
  nickname.value = ''
  password.value = ''
  mode.value = 'login'
  loading.value = false
}

async function handleSubmit() {
  if (!nickname.value.trim() || !password.value) {
    ElMessage.warning('请输入昵称和口令')
    return
  }
  loading.value = true
  try {
    if (mode.value === 'login') {
      await authStore.userLogin(nickname.value.trim(), password.value)
    } else {
      await authStore.register(nickname.value.trim(), password.value)
    }
    visible.value = false
    ElMessage.success(props.fromLoginRequired ? '已登录，请重试操作' : '已登录')
    emit('success')
  } catch (e) {
    if (e?.response?.status === 401) {
      ElMessage.error('昵称或口令错误')
    } else if (e?.response?.status === 409) {
      ElMessage.error('昵称已被注册，请换一个或直接登录')
    } else {
      ElMessage.error(extractError(e, mode.value === 'login' ? '登录失败' : '注册失败'))
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-hint {
  color: #e6a23c;
  font-size: 13px;
  margin-bottom: 8px;
  line-height: 1.5;
}
.auth-tabs {
  margin-bottom: 4px;
}
</style>
