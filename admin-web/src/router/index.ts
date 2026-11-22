import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AdminLayout from '@/layout/AdminLayout.vue'
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
        meta: { title: '控制台', icon: 'Odometer', requiresAdmin: true },
      },
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('@/views/accounts/AccountsView.vue'),
        meta: { title: '账号与分配', icon: 'UserFilled', requiresAdmin: true },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/users/UsersView.vue'),
        meta: { title: '小程序用户', icon: 'User', requiresAdmin: true },
      },
      {
        path: 'ai-config',
        name: 'AiConfig',
        component: () => import('@/views/ai/AiConfigView.vue'),
        meta: { title: 'AI 模型配置', icon: 'Cpu', requiresAdmin: true },
      },
      {
        path: 'ai-playground',
        name: 'AiPlayground',
        component: () => import('@/views/ai/AiPlaygroundView.vue'),
        meta: { title: 'AI 调试台', icon: 'ChatDotRound' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/SettingsView.vue'),
        meta: { title: '系统配置', icon: 'Setting', requiresAdmin: true },
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

router.beforeEach(async (to) => {
  const appTitle = import.meta.env.VITE_APP_TITLE || 'AILOVE 管理后台'
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
    return { path: authStore.isAdmin ? '/dashboard' : '/profile' }
  }

  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    return { path: '/profile' }
  }

  return true
})

export default router
