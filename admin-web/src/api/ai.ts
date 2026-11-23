import router from '@/router'
import { getStoredToken, removeStoredToken, request } from '@/utils/request'

export type AIProtocol = 'openai' | 'anthropic'

export interface AIModelPreset {
  id: string
  label: string
  description: string
  context_window: number
  supports_reasoning: boolean
  supports_temperature: boolean
  default_max_tokens: number
}

export interface AIProviderInfo {
  code: string
  name: string
  protocol: string
  default_protocol?: AIProtocol
  protocol_endpoints?: Record<string, string>
  status: 'active' | 'planned'
  description: string
  default_base_url: string
  docs_url: string
  api_key_placeholder: string
  models: AIModelPreset[]
}

export interface AIModelConfigItem {
  id: number
  name: string
  provider: string
  protocol: AIProtocol
  model_name: string
  base_url: string
  has_api_key: boolean
  api_key_masked: string
  temperature: number
  top_p: number
  max_tokens: number
  timeout_seconds: number
  max_history_messages: number
  system_prompt: string
  extra_params: Record<string, unknown>
  is_enabled: boolean
  is_default: boolean
  last_test_status: 'untested' | 'ok' | 'failed'
  last_test_latency_ms: number | null
  last_test_message: string
  last_tested_at: string | null
  updated_at: string | null
}

export interface AITestResult {
  success: boolean
  latency_ms: number
  model: string
  provider: string
  protocol?: AIProtocol
  reply_preview: string
  message: string
}

export interface AvailableAIModel {
  id: number
  name: string
  provider: string
  protocol: AIProtocol
  model_name: string
  is_default: boolean
  has_api_key: boolean
  supports_reasoning: boolean
  last_test_status: string
}

export interface AiChatPayload {
  message: string
  session_id?: string
  config_id?: number
  persona_id?: number
  system_prompt?: string
  temperature?: number
  timezone?: string
}

export interface AiChatResult {
  session_id: string
  reply: string
  reasoning: string
  model: string
  provider: string
  protocol?: AIProtocol
  config_id: number | null
  config_name: string
  persona_id?: number | null
  persona_name?: string
  is_mock: boolean
  history_length: number
  token_usage: number
}

export type PersonaCategory = 'general' | 'writing' | 'coding' | 'translate' | 'analysis'

export interface AIPersonaItem {
  id: number
  code: string
  name: string
  avatar_emoji: string
  category: PersonaCategory
  description: string
  system_prompt: string
  starter_prompts: string[]
  temperature: number | null
  is_system: boolean
  is_enabled: boolean
  sort_order: number
  usage_count: number
  created_at?: string | null
  updated_at?: string | null
}

export interface AIPersonaPayload {
  code?: string
  name: string
  avatar_emoji: string
  category: PersonaCategory
  description: string
  system_prompt: string
  starter_prompts: string[]
  temperature?: number | null
  clear_temperature?: boolean
  is_enabled: boolean
  sort_order: number
}

export interface AIUserQuota {
  owner_scope: string
  role: string
  is_exempt: boolean
  date: string
  requests_used: number
  requests_limit: number
  requests_remaining: number | null
  tokens_used: number
  tokens_limit: number
  tokens_remaining: number | null
}

export interface AIAnalyticsData {
  days: number
  summary: {
    total_requests: number
    success_requests: number
    failed_requests: number
    today_requests: number
    total_tokens: number
    today_tokens: number
    avg_latency_ms: number
    active_users: number
  }
  daily_trend: Array<{
    date: string
    label: string
    requests: number
    tokens: number
    avg_latency_ms: number
  }>
  by_model: Array<{
    model_name: string
    provider: string
    requests: number
    tokens: number
    share_percent: number
  }>
  top_users: Array<{
    owner_scope: string
    username: string
    requests: number
    tokens: number
  }>
  top_personas: Array<{
    persona_id: number | null
    persona_name: string
    requests: number
    tokens: number
  }>
}

export interface AIConversationItem {
  session_id: string
  title: string
  model_name: string
  created_at: string
  updated_at: string
}

export interface AIConversationMessage {
  id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  token_usage?: number
  created_at?: string
}

// --- 管理端 AI 模型配置 API ---
export function fetchAiProviders() {
  return request<{ items: AIProviderInfo[] }>({
    url: '/admin/ai/providers',
    method: 'get',
  })
}

export function fetchAiConfigs() {
  return request<{ items: AIModelConfigItem[] }>({
    url: '/admin/ai/configs',
    method: 'get',
  })
}

export function createAiConfig(data: {
  name: string
  provider: string
  protocol: AIProtocol
  model_name: string
  base_url: string
  api_key: string
  temperature: number
  top_p: number
  max_tokens: number
  timeout_seconds: number
  max_history_messages: number
  system_prompt: string
  is_enabled: boolean
  is_default: boolean
}) {
  return request<AIModelConfigItem>({
    url: '/admin/ai/configs',
    method: 'post',
    data,
  })
}

export function updateAiConfig(
  configId: number,
  data: {
    name?: string
    protocol?: AIProtocol
    model_name?: string
    base_url?: string
    api_key?: string
    clear_api_key?: boolean
    temperature?: number
    top_p?: number
    max_tokens?: number
    timeout_seconds?: number
    max_history_messages?: number
    system_prompt?: string
    is_enabled?: boolean
    is_default?: boolean
  },
) {
  return request<AIModelConfigItem>({
    url: `/admin/ai/configs/${configId}`,
    method: 'put',
    data,
  })
}

export function setDefaultAiConfig(configId: number) {
  return request<AIModelConfigItem>({
    url: `/admin/ai/configs/${configId}/set-default`,
    method: 'post',
  })
}

export function testAiConfig(configId: number) {
  return request<AITestResult>({
    url: `/admin/ai/configs/${configId}/test`,
    method: 'post',
  })
}

export function deleteAiConfig(configId: number) {
  return request<{ id: number; deleted: boolean }>({
    url: `/admin/ai/configs/${configId}`,
    method: 'delete',
  })
}

// --- 对话与模型选择 API ---
export function fetchAvailableModels() {
  return request<{ items: AvailableAIModel[] }>({
    url: '/ai/models',
    method: 'get',
  })
}

export function sendAiChat(data: AiChatPayload) {
  return request<AiChatResult>({
    url: '/ai/chat',
    method: 'post',
    data,
  })
}

export function clearAiSession(sessionId: string) {
  return request<{ session_id: string; cleared: boolean }>({
    url: `/ai/sessions/${encodeURIComponent(sessionId)}`,
    method: 'delete',
  })
}

export function fetchAiConversations() {
  return request<{ items: AIConversationItem[] }>({
    url: '/ai/conversations',
    method: 'get',
  })
}

export function fetchConversationMessages(sessionId: string) {
  return request<{
    session_id: string
    title: string
    model_name: string
    messages: AIConversationMessage[]
  }>({
    url: `/ai/conversations/${encodeURIComponent(sessionId)}/messages`,
    method: 'get',
  })
}

export function renameAiConversation(sessionId: string, title: string) {
  return request<{ session_id: string; title: string; model_name: string }>({
    url: `/ai/conversations/${encodeURIComponent(sessionId)}`,
    method: 'patch',
    data: { title },
  })
}

export function deleteAiConversation(sessionId: string) {
  return request<{ session_id: string; deleted: boolean }>({
    url: `/ai/conversations/${encodeURIComponent(sessionId)}`,
    method: 'delete',
  })
}

export function fetchPublicPersonas(category?: string) {
  return request<{ items: AIPersonaItem[]; total: number }>({
    url: '/ai/personas',
    method: 'get',
    params: category && category !== 'all' ? { category } : undefined,
  })
}

export function fetchMyAiQuota() {
  return request<AIUserQuota>({
    url: '/ai/quota',
    method: 'get',
  })
}

export function fetchAdminPersonas(params?: { category?: string; keyword?: string }) {
  return request<{ items: AIPersonaItem[]; total: number }>({
    url: '/admin/ai/personas',
    method: 'get',
    params,
  })
}

export function createAdminPersona(data: AIPersonaPayload) {
  return request<AIPersonaItem>({
    url: '/admin/ai/personas',
    method: 'post',
    data,
  })
}

export function updateAdminPersona(id: number, data: Partial<AIPersonaPayload>) {
  return request<AIPersonaItem>({
    url: `/admin/ai/personas/${id}`,
    method: 'put',
    data,
  })
}

export function deleteAdminPersona(id: number) {
  return request<{ deleted_id: number; name: string }>({
    url: `/admin/ai/personas/${id}`,
    method: 'delete',
  })
}

export function fetchAiAnalytics(days = 7) {
  return request<AIAnalyticsData>({
    url: '/admin/ai/analytics',
    method: 'get',
    params: { days },
  })
}

export async function streamAiChat(
  data: AiChatPayload,
  callbacks: {
    onMeta?: (meta: {
      session_id: string
      model?: string
      provider?: string
      protocol?: AIProtocol
      config_name?: string
      persona_id?: number | null
      persona_name?: string
      is_mock?: boolean
    }) => void
    onReasoning?: (chunk: string) => void
    onDelta: (chunk: string) => void
    onUsage?: (totalTokens: number) => void
    onDone?: (sessionId: string) => void
    onError?: (message: string) => void
  },
  signal?: AbortSignal,
): Promise<void> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = getStoredToken()

  const response = await fetch(`${baseUrl}/ai/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(data),
    signal,
  })

  if (response.status === 401) {
    removeStoredToken()
    void router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
    throw new Error('登录已过期，请重新登录')
  }

  if (!response.ok || !response.body) {
    let detail = ''
    try {
      detail = ((await response.json()) as { message?: string }).message ?? ''
    } catch {
      // 非 JSON 响应体
    }
    throw new Error(detail || `流式请求失败 (HTTP ${response.status})`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatchBlock = (block: string) => {
    const dataLine = block.split('\n').find((line) => line.startsWith('data: '))
    if (!dataLine) return

    let payload: {
      event: string
      session_id?: string
      model?: string
      provider?: string
      protocol?: AIProtocol
      config_name?: string
      persona_id?: number | null
      persona_name?: string
      is_mock?: boolean
      content?: string
      message?: string
    }
    try {
      payload = JSON.parse(dataLine.slice(6))
    } catch {
      return
    }

    if (payload.event === 'meta' && payload.session_id) {
      callbacks.onMeta?.({
        session_id: payload.session_id,
        model: payload.model,
        provider: payload.provider,
        protocol: payload.protocol,
        config_name: payload.config_name,
        persona_id: payload.persona_id,
        persona_name: payload.persona_name,
        is_mock: payload.is_mock,
      })
    } else if (payload.event === 'reasoning' && payload.content) {
      callbacks.onReasoning?.(payload.content)
    } else if (payload.event === 'delta' && payload.content) {
      callbacks.onDelta(payload.content)
    } else if (payload.event === 'usage' && payload.content) {
      callbacks.onUsage?.(Number(payload.content) || 0)
    } else if (payload.event === 'done' && payload.session_id) {
      callbacks.onDone?.(payload.session_id)
    } else if (payload.event === 'error') {
      callbacks.onError?.(payload.message || '流式生成发生错误')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    blocks.forEach(dispatchBlock)
  }

  // 处理末尾未以空行结束的残留事件
  buffer += decoder.decode()
  if (buffer.trim()) {
    dispatchBlock(buffer)
  }
}
