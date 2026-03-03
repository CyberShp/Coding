import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

const TOKEN_KEY = 'admin_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')

  const isAdmin = computed(() => !!token.value)

  async function login(username, password) {
    const res = await api.login(username, password)
    token.value = res.data.token
    localStorage.setItem(TOKEN_KEY, res.data.token)
    return res.data
  }

  function logout() {
    token.value = ''
    localStorage.removeItem(TOKEN_KEY)
  }

  async function checkAuth() {
    if (!token.value) return false
    try {
      await api.getAuthMe()
      return true
    } catch {
      logout()
      return false
    }
  }

  return {
    token,
    isAdmin,
    login,
    logout,
    checkAuth,
  }
})
