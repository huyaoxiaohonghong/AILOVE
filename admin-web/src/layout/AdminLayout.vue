<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import BrandLogo from '@/components/BrandLogo.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

interface NavGroup {
  label: string
  items: Array<{ path: string; title: string; icon: string; adminOnly: boolean }>
}

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

const navGroups: NavGroup[] = [
  {
    label: '核心概览',
    items: [{ path: '/dashboard', title: '控制台', icon: 'Odometer', adminOnly: true }],
  },
  {
    label: '账号与风控',
    items: [
      { path: '/accounts', title: '账号与分配', icon: 'UserFilled', adminOnly: true },
      { path: '/users', title: '小程序用户', icon: 'User', adminOnly: true },
      { path: '/profile', title: '个人与安全', icon: 'Postcard', adminOnly: false },
    ],
  },
  {
    label: '智能与系统',
    items: [
      { path: '/ai-config', title: 'AI 模型配置', icon: 'Cpu', adminOnly: true },
      { path: '/ai-playground', title: 'AI 调试台', icon: 'ChatDotRound', adminOnly: false },
      { path: '/settings', title: '系统配置', icon: 'Setting', adminOnly: true },
    ],
  },
]

const visibleGroups = computed(() =>
  navGroups
    .map((g) => ({
      label: g.label,
      items: g.items.filter((item) => !item.adminOnly || authStore.isAdmin),
    }))
    .filter((g) => g.items.length > 0),
)

const activePath = computed(() => route.path)
const currentTitle = computed(() => (route.meta.title as string) || '控制台')

onMounted(() => {
  if (!authStore.user && authStore.isAuthenticated) {
    void authStore.loadProfile()
  }
})

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确认退出当前设备的登录状态？其他已登录设备不会受影响。', '退出登录', {
      confirmButtonText: '退出当前设备',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await authStore.logout()
    ElMessage.success('当前设备已安全退出')
    await router.replace('/login')
  } catch {
    // 取消
  }
}
</script>

<template>
  <el-container class="workspace-layout">
    <el-aside :width="appStore.sidebarCollapsed ? '72px' : '236px'" class="workspace-aside">
      <div class="brand-bar" :class="{ 'is-collapsed': appStore.sidebarCollapsed }">
        <BrandLogo :size="34" />
        <div v-show="!appStore.sidebarCollapsed" class="brand-meta">
          <div class="brand-name">AILOVE</div>
          <div class="brand-sub">{{ authStore.isAdmin ? '管理与风控中台' : '智能协同工作台' }}</div>
        </div>
      </div>

      <nav class="nav-scroll" aria-label="主导航">
        <div v-for="group in visibleGroups" :key="group.label" class="nav-group">
          <div v-show="!appStore.sidebarCollapsed" class="nav-group-label">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.path"
            type="button"
            class="nav-item"
            :class="{ 'is-active': activePath === item.path, 'is-collapsed': appStore.sidebarCollapsed }"
            :title="appStore.sidebarCollapsed ? item.title : undefined"
            @click="router.push(item.path)"
          >
            <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
            <span v-show="!appStore.sidebarCollapsed" class="nav-text">{{ item.title }}</span>
          </button>
        </div>
      </nav>

      <div v-show="!appStore.sidebarCollapsed" class="aside-footer">
        <div class="session-pill">
          <span class="status-dot is-live" />
          <span>24h 会话守护已开启</span>
        </div>
      </div>
    </el-aside>

    <el-container class="workspace-body">
      <el-header class="workspace-header">
        <div class="header-left">
          <button
            type="button"
            class="collapse-btn"
            aria-label="切换侧边栏"
            @click="appStore.toggleSidebar"
          >
            <el-icon size="18">
              <Expand v-if="appStore.sidebarCollapsed" />
              <Fold v-else />
            </el-icon>
          </button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>AILOVE</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <span class="role-badge" :class="authStore.isAdmin ? 'is-admin' : 'is-user'">
            {{ authStore.isAdmin ? '管理员' : '注册用户' }}
          </span>

          <el-dropdown trigger="click">
            <div class="user-pill">
              <div class="user-avatar">
                {{ (authStore.user?.nickname || 'U').slice(0, 1).toUpperCase() }}
              </div>
              <span class="user-name">{{ authStore.user?.nickname || '用户' }}</span>
              <el-icon class="caret"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ authStore.user?.email || authStore.user?.username || '-' }}
                </el-dropdown-item>
                <el-dropdown-item @click="router.push('/profile')">个人与安全中心</el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">退出当前设备</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="workspace-content">
        <div class="content-container">
          <RouterView />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.workspace-layout {
  width: 100%;
  height: 100vh;
  background: var(--ailove-canvas);
}

.workspace-aside {
  background: var(--ailove-subtle);
  border-right: 1px solid var(--ailove-border);
  transition: width 0.22s var(--ailove-ease);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand-bar {
  height: 66px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid var(--ailove-border);
}

.brand-bar.is-collapsed {
  justify-content: center;
  padding: 0;
}

.brand-meta {
  min-width: 0;
}

.brand-name {
  font-family: var(--ailove-font-display);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.03em;
  color: var(--ailove-ink-primary);
}

.brand-sub {
  font-size: 11px;
  color: var(--ailove-ink-muted);
  margin-top: 1px;
  white-space: nowrap;
}

.nav-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ailove-ink-muted);
  letter-spacing: 0.04em;
  padding: 0 10px 4px;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--ailove-ink-secondary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.16s var(--ailove-ease);
}

.nav-item.is-collapsed {
  justify-content: center;
  padding: 0;
}

.nav-item:hover {
  background: rgba(26, 22, 29, 0.04);
  color: var(--ailove-ink-primary);
}

.nav-item.is-active {
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  font-weight: 600;
}

.nav-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 4px 4px 0;
  background: var(--ailove-brand-600);
}

.nav-icon {
  font-size: 17px;
  flex-shrink: 0;
}

.nav-text {
  white-space: nowrap;
}

.aside-footer {
  padding: 12px 14px 16px;
  border-top: 1px solid var(--ailove-border);
}

.session-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--ailove-surface);
  border: 1px solid var(--ailove-border);
  font-size: 12px;
  color: var(--ailove-ink-secondary);
}

.workspace-body {
  min-width: 0;
  background: var(--ailove-canvas);
}

.workspace-header {
  height: 66px;
  background: rgba(247, 244, 241, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--ailove-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.collapse-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 1px solid var(--ailove-border);
  background: var(--ailove-surface);
  color: var(--ailove-ink-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.16s var(--ailove-ease);
}

.collapse-btn:hover {
  border-color: var(--ailove-border-strong);
  color: var(--ailove-ink-primary);
}

.role-badge {
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
}

.role-badge.is-admin {
  background: var(--ailove-accent-amber-bg);
  color: var(--ailove-warning);
  border: 1px solid var(--ailove-warning-border);
}

.role-badge.is-user {
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  border: 1px solid var(--ailove-brand-100);
}

.user-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: 999px;
  background: var(--ailove-surface);
  border: 1px solid var(--ailove-border);
  cursor: pointer;
  transition: border-color 0.16s;
}

.user-pill:hover {
  border-color: var(--ailove-brand-200);
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #e14b68, #c83553);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--ailove-ink-primary);
}

.caret {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.workspace-content {
  padding: 24px;
  overflow-y: auto;
}

.content-container {
  max-width: 1320px;
  margin: 0 auto;
}
</style>
