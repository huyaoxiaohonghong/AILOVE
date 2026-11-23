import { request } from '@/utils/request'

export interface ServiceStatus {
  healthy: boolean
  status: string
}

export interface LangChainStatus {
  configured: boolean
  provider: string
  protocol?: string
  model: string
  base_url: string
}

export interface DashboardOverview {
  stats: {
    platform_user_count: number
    email_registered_count: number
    admin_assigned_count: number
    active_session_count: number
    wechat_user_count: number
    admin_user_count: number
    ai_conversation_count: number
    ai_message_count: number
    db_connected: boolean
  }
  services: {
    mysql: ServiceStatus
    redis: ServiceStatus
    langchain: LangChainStatus
    wechat: { configured: boolean }
  }
}

export interface HealthData {
  status: string
  app: string
  env: string
  timestamp: string
  services: DashboardOverview['services']
}

export interface PublicSystemConfig {
  site_name: string
  site_subtitle: string
  announcement: string
  maintenance_mode: boolean
  registration_enabled: boolean
  slider_captcha_enabled: boolean
  configs: Record<string, unknown>
}

export interface SysConfigItem {
  config_key: string
  group_name: string
  label: string
  value_type: 'string' | 'int' | 'float' | 'bool' | 'json'
  value: string | number | boolean
  default_value: string | number | boolean
  description: string
  is_public: boolean
  min_val: number | null
  max_val: number | null
  updated_at: string | null
}

export interface SysConfigGroup {
  group: string
  label: string
  items: SysConfigItem[]
}

export function fetchHealth() {
  return request<HealthData>({
    url: '/health',
    method: 'get',
  })
}

export function fetchDashboardOverview() {
  return request<DashboardOverview>({
    url: '/admin/dashboard/overview',
    method: 'get',
  })
}

export function fetchPublicConfig() {
  return request<PublicSystemConfig>({
    url: '/system/public-config',
    method: 'get',
  })
}

export function fetchSystemConfigs() {
  return request<{ groups: SysConfigGroup[] }>({
    url: '/admin/system/configs',
    method: 'get',
  })
}

export function updateSystemConfigs(items: Record<string, string | number | boolean>) {
  return request<{ groups: SysConfigGroup[] }>({
    url: '/admin/system/configs',
    method: 'put',
    data: { items },
  })
}

export function resetSystemConfigs(groupName?: string) {
  return request<{ groups: SysConfigGroup[] }>({
    url: '/admin/system/configs/reset',
    method: 'post',
    data: { group_name: groupName || null },
  })
}
