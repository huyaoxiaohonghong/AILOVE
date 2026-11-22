import { request } from '@/utils/request'

export interface WechatUserItem {
  id: number
  openid: string
  nickname: string
  avatar_url: string
  phone: string | null
  status: number
  last_login_at: string | null
  created_at: string | null
}

export interface WechatUserPageResult {
  items: WechatUserItem[]
  total: number
  page: number
  page_size: number
  db_connected: boolean
}

export function fetchWechatUsers(params: {
  page: number
  page_size: number
  keyword?: string
  status?: number | ''
}) {
  const query: Record<string, string | number> = {
    page: params.page,
    page_size: params.page_size,
  }
  if (params.keyword?.trim()) query.keyword = params.keyword.trim()
  if (params.status !== '' && params.status !== undefined) query.status = params.status

  return request<WechatUserPageResult>({
    url: '/admin/users',
    method: 'get',
    params: query,
  })
}

export function updateWechatUserStatus(userId: number, status: number) {
  return request<{ id: number; status: number }>({
    url: `/admin/users/${userId}/status`,
    method: 'patch',
    data: { status },
  })
}
