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
