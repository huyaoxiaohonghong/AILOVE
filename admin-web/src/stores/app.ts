import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchPublicConfig, type PublicSystemConfig } from '@/api/system'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const publicConfig = ref<PublicSystemConfig>({
    site_name: 'AILOVE',
    site_subtitle: '管理与风控中台',
    announcement: '',
    maintenance_mode: false,
    registration_enabled: true,
    slider_captcha_enabled: true,
    configs: {},
  })

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  async function loadPublicConfig() {
    try {
      publicConfig.value = await fetchPublicConfig()
    } catch {
      // 保留默认站点配置
    }
  }

  return {
    sidebarCollapsed,
    publicConfig,
    toggleSidebar,
    loadPublicConfig,
  }
})
