import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  fetchCurrentUser,
  loginAccount,
  logoutAccount,
  registerByEmail,
  type UserProfile,
} from '@/api/auth'
import { getStoredToken, removeStoredToken, setStoredToken } from '@/utils/request'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(getStoredToken())
  const user = ref<UserProfile | null>(null)

  const isAuthenticated = computed(() => Boolean(token.value))
  const isAdmin = computed(
    () => user.value?.role === 'super_admin' || user.value?.role === 'admin',
  )

  async function login(account: string, password: string, captchaToken: string) {
    const res = await loginAccount({ account, password, captcha_token: captchaToken })
    token.value = res.access_token
    user.value = res.user
    setStoredToken(res.access_token)
    return res
  }

  async function register(payload: {
    email: string
    password: string
    nickname?: string
    captcha_token: string
  }) {
    const res = await registerByEmail(payload)
    token.value = res.access_token
    user.value = res.user
    setStoredToken(res.access_token)
    return res
  }

  async function loadProfile() {
    if (!token.value) return null
    try {
      const profile = await fetchCurrentUser()
      user.value = profile
      return profile
    } catch {
      clearSession()
      return null
    }
  }

  async function logout() {
    try {
      if (token.value) {
        await logoutAccount()
      }
    } finally {
      clearSession()
    }
  }

  function clearSession() {
    token.value = ''
    user.value = null
    removeStoredToken()
  }

  return {
    token,
    user,
    isAuthenticated,
    isAdmin,
    login,
    register,
    loadProfile,
    logout,
    clearSession,
  }
})
