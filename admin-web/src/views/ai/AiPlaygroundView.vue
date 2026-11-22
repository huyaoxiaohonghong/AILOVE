<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  clearAiSession,
  fetchAvailableModels,
  sendAiChat,
  streamAiChat,
  type AvailableAIModel,
} from '@/api/ai'

interface ChatBubble {
  id: number
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  modelLabel?: string
  tokenUsage?: number
  isError?: boolean
}

const availableModels = ref<AvailableAIModel[]>([])
const selectedConfigId = ref<number | undefined>(undefined)
const sessionId = ref('')
const inputText = ref('')
const systemPrompt = ref('')
const useStream = ref(true)
const sending = ref(false)
let abortController: AbortController | null = null
const messages = ref<ChatBubble[]>([
  {
    id: 1,
    role: 'assistant',
    content:
      '你好！这里是 AILOVE LangChain 对话调试台，默认接入 DeepSeek（deepseek-flash / deepseek-v4-pro），同时支持 OpenAI 与 Anthropic 双协议、SSE 流式及深度思考链展示。',
  },
])

const listRef = ref<HTMLElement | null>(null)

const currentModel = computed(
  () => availableModels.value.find((m) => m.id === selectedConfigId.value) ?? null,
)

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

async function scrollToBottom() {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  inputText.value = ''
  sending.value = true

  messages.value.push({ id: Date.now(), role: 'user', content: text })
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
              assistantMsg.modelLabel = `${meta.config_name || 'AI'} (${meta.model})${meta.is_mock ? ' · 演示' : ''}`
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
      assistantMsg.modelLabel = `${res.config_name || 'AI'} (${res.model})${res.is_mock ? ' · 演示' : ''}`
      await scrollToBottom()
    }
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

function handleStop() {
  abortController?.abort()
}

async function handleClear() {
  if (sessionId.value) {
    await clearAiSession(sessionId.value)
  }
  sessionId.value = ''
  messages.value = [
    {
      id: Date.now(),
      role: 'assistant',
      content: '已开启全新会话，请输入你想测试的 Prompt。',
    },
  ]
}

onMounted(() => {
  void loadModels()
})

onBeforeUnmount(() => {
  abortController?.abort()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">LangChain AI 调试台</h2>
        <p class="page-subtitle">
          直接切换已配置的 DeepSeek (deepseek-flash / deepseek-v4-pro) 模型与 OpenAI / Anthropic 协议，支持 SSE 流式与深度思考链
        </p>
      </div>
      <div class="toolbar-actions">
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
        <el-button @click="handleClear">清空会话</el-button>
      </div>
    </div>

    <div class="page-card playground-card">
      <div class="prompt-row">
        <el-input
          v-model="systemPrompt"
          placeholder="可选：临时覆盖 System Prompt（留空自动采用所选模型配置中的默认人设）"
          clearable
        >
          <template #prepend>System Prompt</template>
        </el-input>
        <el-tag v-if="sessionId" type="info" effect="plain" class="mono-num">
          SID: {{ sessionId.slice(0, 10) }}
        </el-tag>
      </div>

      <div ref="listRef" class="message-list">
        <div
          v-for="msg in messages"
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
            <div class="bubble-text" :class="{ 'is-error': msg.isError }">
              {{ msg.content || (msg.reasoning ? '正在整理最终回答...' : '正在思考...') }}
            </div>
            <div v-if="msg.tokenUsage" class="bubble-meta mono-num">Tokens · {{ msg.tokenUsage }}</div>
          </div>
        </div>
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

.playground-card {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 196px);
  min-height: 480px;
}

.prompt-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
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
  max-width: 78%;
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
  margin-bottom: 5px;
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

.bubble-text {
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-text.is-error {
  color: var(--el-color-danger);
}

.bubble-meta {
  margin-top: 6px;
  font-size: 11px;
  color: var(--ailove-ink-muted);
}

.composer {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  align-items: stretch;
}

.send-btn {
  width: 96px;
  height: auto;
  border-radius: 10px;
}
</style>
