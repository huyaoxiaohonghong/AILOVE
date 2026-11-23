<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import {
  deleteAiConversation,
  fetchAiConversations,
  fetchAvailableModels,
  fetchConversationMessages,
  fetchMyAiQuota,
  fetchPublicPersonas,
  renameAiConversation,
  sendAiChat,
  streamAiChat,
  type AIConversationItem,
  type AIPersonaItem,
  type AIUserQuota,
  type AvailableAIModel,
} from '@/api/ai'
import { decodeUtf8Base64, renderMarkdown } from '@/utils/markdown'

interface ChatBubble {
  id: number
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  modelLabel?: string
  tokenUsage?: number
  isError?: boolean
}

const WELCOME_MSG: ChatBubble = {
  id: 1,
  role: 'assistant',
  content:
    '你好！这里是 **AILOVE 恋爱情感 AI 对话工作台**，可在上方快速切换「高情商恋爱军师 / 心动约会策划师 / 亲密关系顾问 / 吵架降温调解员 / 深夜情绪树洞」等情感智能体，也支持自由直连对话。\n\n- 默认接入 `deepseek-flash` / `deepseek-v4-pro`\n- 自动注入实时系统时钟上下文与历史多会话记忆\n- 支持思考链展示、Markdown 排版、复制与重新生成',
}

const route = useRoute()

const availableModels = ref<AvailableAIModel[]>([])
const selectedConfigId = ref<number | undefined>(undefined)
const personas = ref<AIPersonaItem[]>([])
const selectedPersonaId = ref<number | undefined>(undefined)
const plazaDrawerVisible = ref(false)
const plazaCategory = ref('all')
const quota = ref<AIUserQuota | null>(null)
const conversations = ref<AIConversationItem[]>([])
const conversationsLoading = ref(false)
const sidebarVisible = ref(true)

const sessionId = ref('')
const inputText = ref('')
const systemPrompt = ref('')
const useStream = ref(true)
const sending = ref(false)
const loadingHistory = ref(false)
let abortController: AbortController | null = null

const messages = ref<ChatBubble[]>([{ ...WELCOME_MSG }])
const listRef = ref<HTMLElement | null>(null)

const currentModel = computed(
  () => availableModels.value.find((m) => m.id === selectedConfigId.value) ?? null,
)

const activePersona = computed(
  () => personas.value.find((p) => p.id === selectedPersonaId.value) ?? null,
)

const plazaFilteredPersonas = computed(() =>
  plazaCategory.value === 'all'
    ? personas.value
    : personas.value.filter((p) => p.category === plazaCategory.value),
)

const quotaSummaryText = computed(() => {
  const q = quota.value
  if (!q) return ''
  if (q.is_exempt) {
    return `配额豁免 · 今日 ${q.requests_used} 次`
  }
  if (q.requests_limit > 0) {
    return `今日剩余 ${q.requests_remaining ?? 0}/${q.requests_limit} 次`
  }
  return `今日已用 ${q.requests_used} 次`
})

const lastAssistantIdx = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i]?.role === 'assistant') return i
  }
  return -1
})

async function loadModels() {
  try {
    const res = await fetchAvailableModels()
    availableModels.value = res.items
    const def = res.items.find((m) => m.is_default) ?? res.items[0]
    if (def && selectedConfigId.value === undefined) {
      selectedConfigId.value = def.id
    }
  } catch {
    // 忽略
  }
}

async function loadPersonas() {
  try {
    const res = await fetchPublicPersonas()
    personas.value = res.items
    const qPid = Number(route.query.personaId)
    if (Number.isFinite(qPid) && qPid > 0) {
      const matched = res.items.find((p) => p.id === qPid)
      if (matched) {
        selectedPersonaId.value = matched.id
      }
    }
  } catch {
    // 忽略
  }
}

async function loadQuota() {
  try {
    quota.value = await fetchMyAiQuota()
  } catch {
    // 忽略
  }
}

function selectPersona(pid?: number) {
  selectedPersonaId.value = pid
  plazaDrawerVisible.value = false
}

async function quickAskStarter(promptText: string) {
  if (!promptText || sending.value) return
  await sendPromptText(promptText, true)
}

async function loadConversations() {
  conversationsLoading.value = true
  try {
    const res = await fetchAiConversations()
    conversations.value = res.items
  } catch {
    // 忽略
  } finally {
    conversationsLoading.value = false
  }
}

async function selectConversation(conv: AIConversationItem) {
  if (sending.value) return
  loadingHistory.value = true
  try {
    const detail = await fetchConversationMessages(conv.session_id)
    sessionId.value = detail.session_id
    messages.value = detail.messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m, idx) => ({
        id: m.id ?? idx + 1,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        modelLabel: m.role === 'assistant' ? detail.model_name || 'AI' : undefined,
        tokenUsage: m.token_usage || undefined,
      }))
    if (messages.value.length === 0) {
      messages.value = [{ ...WELCOME_MSG }]
    }
    await scrollToBottom()
  } finally {
    loadingHistory.value = false
  }
}

function handleNewConversation() {
  if (sending.value) {
    abortController?.abort()
  }
  sessionId.value = ''
  messages.value = [
    {
      id: Date.now(),
      role: 'assistant',
      content: '已开启全新会话，请输入你想探索或提问的内容。',
    },
  ]
}

async function handleRenameConversation(conv: AIConversationItem) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      inputValue: conv.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPattern: /^.{1,120}$/,
      inputErrorMessage: '标题长度须为 1~120 字符',
    })
    const res = await renameAiConversation(conv.session_id, value)
    conv.title = res.title
    ElMessage.success('会话标题已更新')
  } catch {
    // 取消
  }
}

async function handleDeleteConversation(conv: AIConversationItem) {
  try {
    await ElMessageBox.confirm(`确认删除历史会话「${conv.title}」？删除后不可恢复。`, '删除确认', {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteAiConversation(conv.session_id)
    ElMessage.success('会话已删除')
    if (sessionId.value === conv.session_id) {
      handleNewConversation()
    }
    await loadConversations()
  } catch {
    // 取消
  }
}

async function scrollToBottom() {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}

async function sendPromptText(text: string, appendUserBubble = true) {
  if (!text || sending.value) return
  sending.value = true

  if (appendUserBubble) {
    messages.value.push({ id: Date.now(), role: 'user', content: text })
  }
  const assistantMsg: ChatBubble = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    reasoning: '',
    modelLabel: currentModel.value
      ? `${currentModel.value.name} (${currentModel.value.model_name})`
      : 'AILOVE Assistant',
  }
  messages.value.push(assistantMsg)
  await scrollToBottom()

  try {
    const clientTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
    const payload = {
      message: text,
      session_id: sessionId.value || undefined,
      config_id: selectedConfigId.value,
      persona_id: selectedPersonaId.value,
      system_prompt: systemPrompt.value.trim() || undefined,
      timezone: clientTz,
    }

    if (useStream.value) {
      abortController = new AbortController()
      await streamAiChat(
        payload,
        {
          onMeta: (meta) => {
            sessionId.value = meta.session_id
            if (meta.model) {
              const pPrefix = meta.persona_name ? `${meta.persona_name} · ` : ''
              assistantMsg.modelLabel = `${pPrefix}${meta.config_name || 'AI'} (${meta.model})${meta.is_mock ? ' · 演示' : ''}`
            }
          },
          onReasoning: (chunk) => {
            assistantMsg.reasoning = (assistantMsg.reasoning || '') + chunk
            void scrollToBottom()
          },
          onDelta: (chunk) => {
            assistantMsg.content += chunk
            void scrollToBottom()
          },
          onUsage: (total) => {
            assistantMsg.tokenUsage = total
          },
          onError: (errMsg) => {
            assistantMsg.isError = true
            assistantMsg.content = assistantMsg.content
              ? `${assistantMsg.content}\n\n⚠️ ${errMsg}`
              : `⚠️ ${errMsg}`
          },
        },
        abortController.signal,
      )
    } else {
      const res = await sendAiChat(payload)
      sessionId.value = res.session_id
      assistantMsg.reasoning = res.reasoning || ''
      assistantMsg.content = res.reply
      assistantMsg.tokenUsage = res.token_usage || undefined
      const pPrefix = res.persona_name ? `${res.persona_name} · ` : ''
      assistantMsg.modelLabel = `${pPrefix}${res.config_name || 'AI'} (${res.model})${res.is_mock ? ' · 演示' : ''}`
      await scrollToBottom()
    }
    void Promise.all([loadConversations(), loadQuota()])
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      assistantMsg.content = assistantMsg.content
        ? `${assistantMsg.content}\n\n（已停止生成）`
        : '（已停止生成）'
    } else {
      assistantMsg.isError = true
      assistantMsg.content = `请求出错：${err instanceof Error ? err.message : '未知错误'}`
    }
  } finally {
    abortController = null
    sending.value = false
  }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return
  inputText.value = ''
  await sendPromptText(text, true)
}

async function handleRegenerate() {
  if (sending.value) return
  let lastUserText = ''
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const item = messages.value[i]
    if (item?.role === 'user') {
      lastUserText = item.content
      break
    }
  }
  if (!lastUserText) return
  if (lastAssistantIdx.value >= 0) {
    messages.value.splice(lastAssistantIdx.value, 1)
  }
  await sendPromptText(lastUserText, false)
}

function handleStop() {
  abortController?.abort()
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('当前浏览器环境不支持自动写入剪贴板')
  }
}

function handleMessageAreaClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const btn = target?.closest('.md-copy-btn') as HTMLButtonElement | null
  if (!btn) return
  const b64 = btn.getAttribute('data-copy-b64') || ''
  const code = decodeUtf8Base64(b64)
  if (code) {
    void copyText(code).then(() => {
      btn.textContent = '已复制'
      setTimeout(() => {
        btn.textContent = '复制代码'
      }, 1500)
    })
  }
}

onMounted(() => {
  void Promise.all([loadModels(), loadPersonas(), loadConversations(), loadQuota()])
})

onBeforeUnmount(() => {
  abortController?.abort()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">LangChain AI 工作台</h2>
        <p class="page-subtitle">
          持久化多会话管理 + Markdown 代码高亮排版，实时切换 DeepSeek 双协议引擎与思考链流
        </p>
      </div>
      <div class="toolbar-actions">
        <el-tag
          v-if="quota"
          :type="quota.is_exempt ? 'warning' : (quota.requests_remaining ?? 1) <= 5 ? 'danger' : 'info'"
          effect="plain"
          class="mono-num quota-pill"
        >
          {{ quotaSummaryText }}
        </el-tag>
        <el-button plain size="small" :icon="MagicStick" @click="plazaDrawerVisible = true">
          智能体广场
        </el-button>
        <el-button plain size="small" @click="sidebarVisible = !sidebarVisible">
          {{ sidebarVisible ? '收起历史栏' : '展开历史栏' }}
        </el-button>
        <el-select
          v-model="selectedConfigId"
          placeholder="选择模型配置"
          style="width: 240px"
        >
          <el-option
            v-for="m in availableModels"
            :key="m.id"
            :label="`${m.name} (${m.model_name})`"
            :value="m.id"
          >
            <div class="model-opt">
              <span>{{ m.name }}</span>
              <el-tag
                size="small"
                :type="m.has_api_key ? 'success' : 'warning'"
                effect="plain"
              >
                {{ m.has_api_key ? `${m.model_name} · ${m.protocol}` : '未填Key' }}
              </el-tag>
            </div>
          </el-option>
        </el-select>
        <el-switch v-model="useStream" active-text="SSE 流式" inactive-text="同步" />
        <el-button type="primary" plain icon="Plus" @click="handleNewConversation">新建对话</el-button>
      </div>
    </div>

    <div class="workbench-shell">
      <!-- 左侧历史会话栏 -->
      <aside v-show="sidebarVisible" v-loading="conversationsLoading" class="page-card history-pane">
        <div class="history-head">
          <span>历史会话 ({{ conversations.length }})</span>
          <el-button link type="primary" size="small" icon="Refresh" @click="loadConversations" />
        </div>
        <div v-if="conversations.length === 0" class="history-empty">
          暂无历史会话，发起第一轮对话后将自动持久保存
        </div>
        <div v-else class="history-list">
          <div
            v-for="conv in conversations"
            :key="conv.session_id"
            class="history-item"
            :class="{ 'is-active': sessionId === conv.session_id }"
            @click="selectConversation(conv)"
          >
            <div class="history-title" :title="conv.title">{{ conv.title }}</div>
            <div class="history-meta">
              <span class="mono-num history-model">{{ conv.model_name || 'AI' }}</span>
              <span class="history-ops" @click.stop>
                <el-button
                  link
                  size="small"
                  type="primary"
                  @click="handleRenameConversation(conv)"
                >
                  改名
                </el-button>
                <el-button
                  link
                  size="small"
                  type="danger"
                  @click="handleDeleteConversation(conv)"
                >
                  删
                </el-button>
              </span>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右侧对话主工作台 -->
      <div v-loading="loadingHistory" class="page-card playground-card">
        <div class="prompt-row">
          <el-input
            v-model="systemPrompt"
            :placeholder="
              activePersona
                ? `已激活「${activePersona.name}」人设（留空自动生效，输入可临时覆盖）`
                : '可选：临时覆盖 System Prompt（留空自动采用所选模型配置中的默认人设）'
            "
            clearable
          >
            <template #prepend>System Prompt</template>
          </el-input>
          <el-tag v-if="sessionId" type="info" effect="plain" class="mono-num">
            SID: {{ sessionId.slice(0, 10) }}
          </el-tag>
        </div>

        <div v-if="personas.length > 0" class="persona-bar">
          <button
            type="button"
            class="persona-chip"
            :class="{ 'is-active': selectedPersonaId === undefined }"
            @click="selectPersona(undefined)"
          >
            默认直连
          </button>
          <button
            v-for="p in personas.slice(0, 5)"
            :key="p.id"
            type="button"
            class="persona-chip"
            :class="{ 'is-active': selectedPersonaId === p.id }"
            @click="selectPersona(p.id)"
          >
            <span>{{ p.avatar_emoji }}</span>
            <span>{{ p.name }}</span>
          </button>
          <button
            v-if="personas.length > 5"
            type="button"
            class="persona-chip is-more"
            @click="plazaDrawerVisible = true"
          >
            更多 ({{ personas.length }})
          </button>
        </div>

        <div ref="listRef" class="message-list" @click="handleMessageAreaClick">
          <div
            v-for="(msg, idx) in messages"
            :key="msg.id"
            class="message-row"
            :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
          >
            <div class="bubble">
              <div class="bubble-role">
                {{ msg.role === 'user' ? '我' : msg.modelLabel || 'AILOVE Assistant' }}
              </div>
              <details v-if="msg.reasoning" class="reasoning-box" open>
                <summary>深度思考过程 (Reasoning)</summary>
                <div class="reasoning-text">{{ msg.reasoning }}</div>
              </details>

              <div v-if="msg.role === 'user'" class="bubble-plain">{{ msg.content }}</div>
              <div
                v-else-if="msg.isError || !msg.content"
                class="bubble-plain"
                :class="{ 'is-error': msg.isError }"
              >
                {{ msg.content || (msg.reasoning ? '正在整理最终回答...' : '正在思考...') }}
              </div>
              <div
                v-else
                class="markdown-body"
                v-html="renderMarkdown(msg.content)"
              />

              <div v-if="msg.role === 'assistant' && msg.content" class="bubble-actions">
                <span v-if="msg.tokenUsage" class="bubble-token mono-num">
                  Tokens · {{ msg.tokenUsage }}
                </span>
                <div class="bubble-btns">
                  <button type="button" class="mini-action-btn" @click="copyText(msg.content)">
                    复制全文
                  </button>
                  <button
                    v-if="idx === lastAssistantIdx && idx > 0 && !sending"
                    type="button"
                    class="mini-action-btn"
                    @click="handleRegenerate"
                  >
                    重新生成
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="activePersona?.starter_prompts?.length" class="starter-bar">
          <span class="starter-label">{{ activePersona.avatar_emoji }} 快捷提问：</span>
          <button
            v-for="sp in activePersona.starter_prompts"
            :key="sp"
            type="button"
            class="starter-chip"
            :disabled="sending"
            @click="quickAskStarter(sp)"
          >
            {{ sp }}
          </button>
        </div>

        <div class="composer">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入消息，按 Ctrl/Cmd + Enter 快速发送"
            @keydown.ctrl.enter.prevent="handleSend"
            @keydown.meta.enter.prevent="handleSend"
          />
          <el-button v-if="sending && useStream" class="send-btn" @click="handleStop">
            停止生成
          </el-button>
          <el-button v-else type="primary" :loading="sending" class="send-btn" @click="handleSend">
            发送
          </el-button>
        </div>
      </div>
    </div>

    <el-drawer v-model="plazaDrawerVisible" title="AI 智能体广场" size="420px">
      <div class="plaza-cats">
        <button
          v-for="cat in [
            { k: 'all', l: '全部' },
            { k: 'chat_coach', l: '话术' },
            { k: 'dating', l: '约会' },
            { k: 'relationship', l: '关系' },
            { k: 'conflict', l: '修复' },
            { k: 'healing', l: '疗愈' },
          ]"
          :key="cat.k"
          type="button"
          class="persona-chip"
          :class="{ 'is-active': plazaCategory === cat.k }"
          @click="plazaCategory = cat.k"
        >
          {{ cat.l }}
        </button>
      </div>

      <div class="plaza-list">
        <div
          class="plaza-card"
          :class="{ 'is-active': selectedPersonaId === undefined }"
          @click="selectPersona(undefined)"
        >
          <div class="plaza-card-top">
            <span class="plaza-emoji">✨</span>
            <div>
              <div class="plaza-name">默认直连对话</div>
              <div class="plaza-desc">不使用特定角色，直接采用所选大模型配置与系统提示词</div>
            </div>
          </div>
        </div>

        <div
          v-for="p in plazaFilteredPersonas"
          :key="p.id"
          class="plaza-card"
          :class="{ 'is-active': selectedPersonaId === p.id }"
          @click="selectPersona(p.id)"
        >
          <div class="plaza-card-top">
            <span class="plaza-emoji">{{ p.avatar_emoji }}</span>
            <div style="flex: 1; min-width: 0">
              <div class="plaza-name-row">
                <span class="plaza-name">{{ p.name }}</span>
                <span class="plaza-usage mono-num">{{ p.usage_count }} 次</span>
              </div>
              <div class="plaza-desc">{{ p.description }}</div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.model-opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.workbench-shell {
  display: flex;
  gap: 16px;
  height: calc(100vh - 196px);
  min-height: 500px;
}

.history-pane {
  width: 248px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 14px;
  overflow: hidden;
}

.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
  margin-bottom: 10px;
}

.history-empty {
  font-size: 12.5px;
  color: var(--ailove-ink-muted);
  line-height: 1.6;
  padding: 20px 6px;
  text-align: center;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  padding: 10px 11px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: var(--ailove-subtle);
  cursor: pointer;
  transition: all 0.15s var(--ailove-ease);
}

.history-item:hover {
  border-color: var(--ailove-brand-200);
}

.history-item.is-active {
  background: var(--ailove-brand-50);
  border-color: var(--ailove-brand-200);
}

.history-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ailove-ink-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  margin-top: 5px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.history-model {
  font-size: 11px;
  color: var(--ailove-ink-muted);
}

.history-ops {
  opacity: 0;
  transition: opacity 0.14s;
}

.history-item:hover .history-ops,
.history-item.is-active .history-ops {
  opacity: 1;
}

.playground-card {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.prompt-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  background: var(--ailove-subtle);
  border-radius: 14px;
  border: 1px solid var(--ailove-border);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.message-row {
  display: flex;
}

.message-row.is-user {
  justify-content: flex-end;
}

.bubble {
  max-width: 82%;
  padding: 13px 16px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid var(--ailove-border);
  box-shadow: 0 2px 8px rgba(26, 22, 29, 0.04);
}

.message-row.is-user .bubble {
  background: linear-gradient(135deg, #d84361 0%, #c83553 100%);
  color: #ffffff;
  border-color: transparent;
  box-shadow: var(--ailove-shadow-brand);
}

.bubble-role {
  font-size: 11px;
  font-weight: 600;
  opacity: 0.72;
  margin-bottom: 6px;
}

.reasoning-box {
  margin: 6px 0 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border-left: 3px solid var(--ailove-brand-200);
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
}

.reasoning-box summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--ailove-ink-muted);
  margin-bottom: 4px;
}

.reasoning-text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.bubble-plain {
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-plain.is-error {
  color: var(--el-color-danger);
}

.bubble-actions {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--ailove-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.bubble-token {
  font-size: 11px;
  color: var(--ailove-ink-muted);
}

.bubble-btns {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.mini-action-btn {
  border: none;
  background: transparent;
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
  cursor: pointer;
  transition: all 0.14s;
}

.mini-action-btn:hover {
  background: var(--ailove-subtle);
  color: var(--ailove-brand-600);
}

/* Markdown 富文本排版样式 */
.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--ailove-ink-primary);
  word-break: break-word;
}

.markdown-body :deep(.md-p) {
  margin: 0 0 8px;
}

.markdown-body :deep(.md-p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(.md-h) {
  margin: 12px 0 6px;
  font-family: var(--ailove-font-display);
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.markdown-body :deep(.md-h1) {
  font-size: 18px;
}
.markdown-body :deep(.md-h2) {
  font-size: 16px;
}
.markdown-body :deep(.md-h3),
.markdown-body :deep(.md-h4) {
  font-size: 14.5px;
}

.markdown-body :deep(.md-list) {
  margin: 6px 0 8px;
  padding-left: 20px;
}

.markdown-body :deep(.md-list li) {
  margin: 3px 0;
}

.markdown-body :deep(.md-quote) {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--ailove-brand-400);
  background: var(--ailove-subtle);
  border-radius: 0 8px 8px 0;
  color: var(--ailove-ink-secondary);
}

.markdown-body :deep(.md-hr) {
  border: none;
  border-top: 1px solid var(--ailove-border);
  margin: 12px 0;
}

.markdown-body :deep(.md-inline-code) {
  font-family: var(--ailove-font-mono);
  font-size: 12.5px;
  background: rgba(200, 53, 83, 0.08);
  color: #b52c49;
  padding: 1px 6px;
  border-radius: 5px;
}

.markdown-body :deep(.md-code-block) {
  margin: 8px 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(26, 22, 29, 0.14);
  background: #1d1922;
}

.markdown-body :deep(.md-code-head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #27222d;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.markdown-body :deep(.md-code-lang) {
  font-family: var(--ailove-font-mono);
  font-size: 11px;
  color: #c7bfd0;
  text-transform: lowercase;
}

.markdown-body :deep(.md-copy-btn) {
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: transparent;
  color: #e6e0ec;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.markdown-body :deep(.md-copy-btn:hover) {
  background: rgba(255, 255, 255, 0.1);
}

.markdown-body :deep(.md-pre) {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
  font-family: var(--ailove-font-mono);
  font-size: 12.5px;
  line-height: 1.55;
  color: #f3eff7;
}

.markdown-body :deep(.md-table-wrap) {
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body :deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.markdown-body :deep(.md-table th),
.markdown-body :deep(.md-table td) {
  border: 1px solid var(--ailove-border);
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(.md-table th) {
  background: var(--ailove-subtle);
  font-weight: 600;
}

.markdown-body :deep(.md-link) {
  color: var(--ailove-brand-600);
  text-decoration: underline;
}

.composer {
  margin-top: 14px;
  display: flex;
  gap: 12px;
  align-items: stretch;
}

.send-btn {
  width: 96px;
  height: auto;
  border-radius: 10px;
}

@media (max-width: 900px) {
  .history-pane {
    display: none;
  }
}

.persona-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0 6px;
}

.persona-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--ailove-border);
  background: var(--ailove-subtle);
  color: var(--ailove-ink-secondary);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.16s;
}

.persona-chip:hover {
  border-color: var(--ailove-brand-200);
  color: var(--ailove-brand-600);
}

.persona-chip.is-active {
  background: var(--ailove-brand-50);
  border-color: var(--ailove-brand-500);
  color: var(--ailove-brand-600);
}

.starter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.starter-label {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.starter-chip {
  border: 1px dashed var(--ailove-brand-200);
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.starter-chip:hover:not(:disabled) {
  background: var(--ailove-brand-600);
  color: #ffffff;
}

.plaza-cats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.plaza-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.plaza-card {
  border: 1px solid var(--ailove-border);
  background: var(--ailove-surface);
  border-radius: 12px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.18s;
}

.plaza-card:hover,
.plaza-card.is-active {
  border-color: var(--ailove-brand-500);
  background: var(--ailove-brand-50);
}

.plaza-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.plaza-emoji {
  font-size: 22px;
  line-height: 1.2;
}

.plaza-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.plaza-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.plaza-usage {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.plaza-desc {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
  line-height: 1.5;
}
</style>
