import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AdminLayout from '@/layout/AdminLayout.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { getStoredToken } from '@/utils/request'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { title: '登录与注册', public: true },
  },
  {
    path: '/',
    component: AdminLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '控制台', icon: 'Odometer', requiresAdmin: true, permission: 'dashboard:view' },
      },
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('@/views/accounts/AccountsView.vue'),
        meta: { title: '账号与分配', icon: 'UserFilled', requiresAdmin: true, permission: 'account:view' },
      },
      {
        path: 'rbac',
        name: 'Rbac',
        component: () => import('@/views/rbac/RbacView.vue'),
        meta: { title: '角色与权限', icon: 'Key', requiresAdmin: true, permission: 'rbac:role:view' },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/users/UsersView.vue'),
        meta: {
          title: '小程序用户',
          icon: 'User',
          requiresAdmin: true,
          permission: 'miniapp_user:view',
        },
      },
      {
        path: 'ai-config',
        name: 'AiConfig',
        component: () => import('@/views/ai/AiConfigView.vue'),
        meta: { title: 'AI 模型配置', icon: 'Cpu', requiresAdmin: true, permission: 'ai:config:view' },
      },
      {
        path: 'ai-playground',
        name: 'AiPlayground',
        component: () => import('@/views/ai/AiPlaygroundView.vue'),
        meta: { title: 'AI 调试台', icon: 'ChatDotRound', permission: 'ai:chat' },
      },
      {
        path: 'logs',
        name: 'Logs',
        component: () => import('@/views/logs/LogsView.vue'),
        meta: { title: '日志与审计', icon: 'Document', requiresAdmin: true, permission: 'log:audit:view' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/SettingsView.vue'),
        meta: {
          title: '系统配置',
          icon: 'Setting',
          requiresAdmin: true,
          permission: 'system:config:view',
        },
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/profile/ProfileView.vue'),
        meta: { title: '个人中心', icon: 'Postcard' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

function resolveDefaultLanding(authStore: ReturnType<typeof useAuthStore>): string {
  if (!authStore.isAdminPortal) return '/profile'
  if (authStore.hasPermission('dashboard:view')) return '/dashboard'
  if (authStore.hasPermission('account:view')) return '/accounts'
  if (authStore.hasPermission('log:audit:view')) return '/logs'
  return '/profile'
}

router.beforeEach(async (to) => {
  const appStore = useAppStore()
  const siteName = appStore.publicConfig.site_name || 'AILOVE'
  const appTitle = import.meta.env.VITE_APP_TITLE || `${siteName} 管理后台`
  if (typeof to.meta.title === 'string') {
    document.title = `${to.meta.title} - ${appTitle}`
  }

  const isPublic = Boolean(to.meta.public)
  const hasToken = Boolean(getStoredToken())

  if (!isPublic && !hasToken) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  const authStore = useAuthStore()
  if (hasToken && !authStore.user) {
    await authStore.loadProfile()
  }

  if (to.path === '/login' && authStore.isAuthenticated) {
    return { path: resolveDefaultLanding(authStore) }
  }

  if (to.meta.requiresAdmin && !authStore.isAdminPortal) {
    return { path: '/profile' }
  }

  const requiredPerm = typeof to.meta.permission === 'string' ? to.meta.permission : ''
  if (requiredPerm && authStore.isAuthenticated && !authStore.hasPermission(requiredPerm)) {
    return { path: resolveDefaultLanding(authStore) }
  }

  return true
})

export default router
