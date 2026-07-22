import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

const TOKEN_KEY = 'admin_token'
const USER_TOKEN_KEY = 'user_token'

export const useAuthStore = defineStore('auth', () => {
  // ---- Legacy admin token (emergency backdoor, admin console) ----
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')

  const isAdmin = computed(() => !!token.value || !!currentUser.value?.is_admin)

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

  // ---- Multi-user account (Phase 1) ----
  const userToken = ref(localStorage.getItem(USER_TOKEN_KEY) || '')
  // {id, nickname, is_admin, teams:[tag_id...]} or null when anonymous
  const currentUser = ref(null)

  const isLoggedIn = computed(() => !!userToken.value)

  function _applyAuth(data) {
    userToken.value = data.token
    localStorage.setItem(USER_TOKEN_KEY, data.token)
    currentUser.value = { teams: [], ...data.user }
    return data.user
  }

  async function register(nickname, password) {
    const res = await api.register(nickname, password)
    return _applyAuth(res.data)
  }

  async function userLogin(nickname, password) {
    const res = await api.userLogin(nickname, password)
    return _applyAuth(res.data)
  }

  function userLogout() {
    userToken.value = ''
    currentUser.value = null
    localStorage.removeItem(USER_TOKEN_KEY)
  }

  async function fetchWhoami() {
    if (!userToken.value) {
      currentUser.value = null
      return null
    }
    try {
      const res = await api.whoami()
      if (res.data?.anonymous) {
        // Token no longer recognized by the backend — drop it.
        userLogout()
        return null
      }
      currentUser.value = { teams: [], ...res.data }
      return currentUser.value
    } catch {
      // Network/server error: keep the token, stay optimistic.
      return currentUser.value
    }
  }

  async function setTeams(tagIds) {
    await api.setMyTeams(tagIds)
    if (currentUser.value) {
      currentUser.value = { ...currentUser.value, teams: [...tagIds] }
    }
    return tagIds
  }

  return {
    // legacy admin
    token,
    isAdmin,
    login,
    logout,
    checkAuth,
    // multi-user accounts
    userToken,
    currentUser,
    isLoggedIn,
    register,
    userLogin,
    userLogout,
    fetchWhoami,
    setTeams,
  }
})
