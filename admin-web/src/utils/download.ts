import router from '@/router'
import { getStoredToken, removeStoredToken } from '@/utils/request'

/**
 * 通过携带 JWT 的 fetch 请求下载后端 CSV 文件，并自动触发浏览器另存为。
 */
export async function downloadAuthenticatedCsv(
  endpointPath: string,
  params?: Record<string, string | number | undefined>,
  fallbackFilename = 'export.csv',
): Promise<string> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = getStoredToken()
  const search = new URLSearchParams()
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && String(v).trim() !== '') {
        search.set(k, String(v).trim())
      }
    }
  }
  const qs = search.toString()
  const url = `${baseUrl}${endpointPath}${qs ? `?${qs}` : ''}`

  const resp = await fetch(url, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (resp.status === 401) {
    removeStoredToken()
    void router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
    throw new Error('登录已过期，请重新登录')
  }

  if (!resp.ok) {
    let msg = ''
    try {
      msg = ((await resp.json()) as { message?: string }).message ?? ''
    } catch {
      // 非 JSON 错误体
    }
    throw new Error(msg || `导出失败 (HTTP ${resp.status})`)
  }

  const disposition = resp.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const filename = match?.[1] || fallbackFilename

  const blob = await resp.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
  return filename
}
