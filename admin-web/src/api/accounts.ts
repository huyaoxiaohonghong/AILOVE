import { request } from '@/utils/request'

export interface AccountItem {
  id: number
  username: string | null
  email: string
  canonical_email: string
  nickname: string
  role: string
  register_source: string
  email_provider: string
  email_trust_score: number
  is_active: boolean
  online_sessions: number
  created_by: number | null
  last_login_at: string | null
  created_at: string | null
}

export interface AccountPageResult {
  items: AccountItem[]
  total: number
  page: number
  page_size: number
  db_connected: boolean
}

export function fetchAccounts(params: {
  page: number
  page_size: number
  keyword?: string
  role?: string
  register_source?: string
  is_active?: boolean | ''
}) {
  const query: Record<string, string | number | boolean> = {
    page: params.page,
    page_size: params.page_size,
  }
  if (params.keyword?.trim()) query.keyword = params.keyword.trim()
  if (params.role) query.role = params.role
  if (params.register_source) query.register_source = params.register_source
  if (params.is_active !== '' && params.is_active !== undefined) query.is_active = params.is_active

  return request<AccountPageResult>({
    url: '/admin/accounts',
    method: 'get',
    params: query,
  })
}

export function adminCreateAccount(data: {
  email: string
  password: string
  nickname: string
  username?: string
  role: string
  allow_non_mainstream_email: boolean
}) {
  return request<AccountItem>({
    url: '/admin/accounts',
    method: 'post',
    data,
  })
}

export function updateAccountRole(userId: number, role: string) {
  return request<{ id: number; role: string; role_name: string; kicked_sessions: number }>({
    url: `/admin/accounts/${userId}/role`,
    method: 'patch',
    data: { role },
  })
}

export function updateAccountStatus(userId: number, isActive: boolean) {
  return request<{ id: number; is_active: boolean }>({
    url: `/admin/accounts/${userId}/status`,
    method: 'patch',
    data: { is_active: isActive },
  })
}

export function resetAccountPassword(userId: number, newPassword: string) {
  return request<{ id: number; reset: boolean }>({
    url: `/admin/accounts/${userId}/reset-password`,
    method: 'post',
    data: { new_password: newPassword },
  })
}

export function kickAccountSessions(userId: number) {
  return request<{ id: number; kicked_sessions: number }>({
    url: `/admin/accounts/${userId}/kick`,
    method: 'post',
  })
}
