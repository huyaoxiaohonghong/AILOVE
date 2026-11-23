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
  const permissions = computed<string[]>(() => user.value?.permissions ?? [])
  const isAdminPortal = computed(
    () =>
      Boolean(user.value?.is_admin_portal) ||
      user.value?.role === 'super_admin' ||
      user.value?.role === 'admin' ||
      user.value?.role === 'operator',
  )
  const isAdmin = isAdminPortal

  function hasPermission(code?: string): boolean {
    if (!code) return true
    const perms = permissions.value
    if (perms.includes('*')) return true
    if (perms.length > 0) return perms.includes(code)
    // 兜底兼容：旧缓存无 permissions 字段时按内置管理员角色放行
    return user.value?.role === 'super_admin'
  }

  function hasAnyPermission(codes: string[]): boolean {
    if (!codes.length) return true
    return codes.some((c) => hasPermission(c))
  }

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
    email_code?: string
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
    permissions,
    isAuthenticated,
    isAdminPortal,
    isAdmin,
    hasPermission,
    hasAnyPermission,
    login,
    register,
    loadProfile,
    logout,
    clearSession,
  }
})
