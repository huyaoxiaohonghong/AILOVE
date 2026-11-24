import { downloadAuthenticatedCsv } from '@/utils/download'
import { request } from '@/utils/request'

export interface LogSummary {
  audit_total_24h: number
  audit_alert_24h: number
  login_success_24h: number
  login_failed_24h: number
  by_module: Record<string, number>
}

export interface AuditLogItem {
  id: number
  request_id: string
  user_id: number | null
  username: string
  role: string
  module: string
  action: string
  method: string
  path: string
  status_code: number
  result: 'success' | 'denied' | 'error'
  ip: string
  device_label: string
  duration_ms: number
  request_summary: string
  error_message: string
  created_at: string
}

export interface LoginAuditLogItem {
  id: number
  user_id: number | null
  account: string
  ip: string
  device_label: string
  status: 'success' | 'failed'
  fail_reason: string
  created_at: string
}

export interface LogPageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export function fetchLogSummary() {
  return request<LogSummary>({
    url: '/admin/logs/summary',
    method: 'get',
  })
}

export function fetchAuditLogs(params: {
  page: number
  page_size: number
  keyword?: string
  module?: string
  result?: string
  method?: string
}) {
  const query: Record<string, string | number> = {
    page: params.page,
    page_size: params.page_size,
  }
  if (params.keyword?.trim()) query.keyword = params.keyword.trim()
  if (params.module) query.module = params.module
  if (params.result) query.result = params.result
  if (params.method) query.method = params.method

  return request<LogPageResult<AuditLogItem>>({
    url: '/admin/logs/audit',
    method: 'get',
    params: query,
  })
}

export function fetchAllLoginLogs(params: {
  page: number
  page_size: number
  keyword?: string
  status?: string
}) {
  const query: Record<string, string | number> = {
    page: params.page,
    page_size: params.page_size,
  }
  if (params.keyword?.trim()) query.keyword = params.keyword.trim()
  if (params.status) query.status = params.status

  return request<LogPageResult<LoginAuditLogItem>>({
    url: '/admin/logs/login',
    method: 'get',
    params: query,
  })
}

export function cleanupOldLogs(data: {
  retention_days?: number
  target: 'audit' | 'login' | 'all'
}) {
  return request<{
    retention_days: number
    deleted_audit_logs: number
    deleted_login_logs: number
  }>({
    url: '/admin/logs/cleanup',
    method: 'post',
    data,
  })
}

export function exportAuditLogsCsv(params: {
  keyword?: string
  module?: string
  result?: string
  method?: string
}) {
  return downloadAuthenticatedCsv('/admin/logs/audit/export', params, 'ailove_audit_logs.csv')
}

export function exportLoginLogsCsv(params: { keyword?: string; status?: string }) {
  return downloadAuthenticatedCsv('/admin/logs/login/export', params, 'ailove_login_logs.csv')
}
